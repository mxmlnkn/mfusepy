#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import errno
import os
import struct
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402

# Values for the binary ACL format documented in acl(5) and defined in <linux/posix_acl_xattr.h>.
POSIX_ACL_XATTR_VERSION = 2
ACL_UNDEFINED_ID = 0xFFFF_FFFF
ACL_USER_OBJ = 0x01
ACL_USER = 0x02
ACL_GROUP_OBJ = 0x04
ACL_GROUP = 0x08
ACL_MASK = 0x10
ACL_OTHER = 0x20
ACL_READ = 4
ACL_WRITE = 2
ACL_EXECUTE = 1

ACL_ACCESS_XATTR = 'system.posix_acl_access'
FILE_CONTENTS = b'Hello ACL!\n'


def pack_acl(entries) -> bytes:
    'Pack (tag, permissions, id) triples into the binary format expected by the kernel.'
    return struct.pack('<I', POSIX_ACL_XATTR_VERSION) + b''.join(
        struct.pack('<HHI', tag, permissions, entry_id) for tag, permissions, entry_id in entries
    )


def test_feature_flags():
    connection = mfusepy.fuse_conn_info()

    assert not connection.is_capable(mfusepy.FUSE_CAP_POSIX_ACL)
    assert not connection.is_wanted(mfusepy.FUSE_CAP_POSIX_ACL)
    # Requesting a feature that the kernel is not capable of must not change anything because
    # libfuse aborts the mount with EPROTO for unknown 'want' flags.
    assert not connection.set_feature_flag(mfusepy.FUSE_CAP_POSIX_ACL)
    assert connection.want == 0

    if connection._has_extended_features:
        connection.capable_ext = mfusepy.FUSE_CAP_POSIX_ACL | mfusepy.FUSE_CAP_ASYNC_READ
    else:
        connection.capable = mfusepy.FUSE_CAP_POSIX_ACL | mfusepy.FUSE_CAP_ASYNC_READ

    assert connection.is_capable(mfusepy.FUSE_CAP_POSIX_ACL)
    assert not connection.is_capable(mfusepy.FUSE_CAP_POSIX_ACL | mfusepy.FUSE_CAP_PASSTHROUGH)

    assert connection.set_feature_flag(mfusepy.FUSE_CAP_POSIX_ACL)
    assert connection.is_wanted(mfusepy.FUSE_CAP_POSIX_ACL)
    assert not connection.is_wanted(mfusepy.FUSE_CAP_ASYNC_READ)
    # 'want' must be kept in sync with 'want_ext' for libfuse < 3.17 and also for newer versions,
    # which only convert 'want' into 'want_ext' if exactly one of both has been changed.
    assert connection.want == mfusepy.FUSE_CAP_POSIX_ACL
    if connection._has_extended_features:
        assert connection.want_ext == mfusepy.FUSE_CAP_POSIX_ACL

    connection.unset_feature_flag(mfusepy.FUSE_CAP_POSIX_ACL)
    assert not connection.is_wanted(mfusepy.FUSE_CAP_POSIX_ACL)
    assert connection.want == 0
    if connection._has_extended_features:
        assert connection.want_ext == 0


def test_feature_flag_names():
    assert mfusepy.feature_flag_names(mfusepy.FUSE_CAP_POSIX_ACL) == 'FUSE_CAP_POSIX_ACL'
    assert mfusepy.feature_flag_names(0) == '0x0'
    assert mfusepy.feature_flag_names(mfusepy.FUSE_CAP_POSIX_ACL | mfusepy.FUSE_CAP_ASYNC_READ) == (
        'FUSE_CAP_ASYNC_READ | FUSE_CAP_POSIX_ACL'
    )


class ACLFileSystem(mfusepy.Operations):
    '''
    A read-only file system with two files owned by root, whose access permissions can only be
    decided correctly when the kernel does enforce the returned POSIX ACLs:

      - 'allowed' is not readable according to its mode bits but the ACL grants read access.
      - 'denied' is readable according to its mode bits but the ACL denies read access.
    '''

    use_ns = True
    wanted_features = mfusepy.FUSE_CAP_POSIX_ACL

    def __init__(self):
        user_id = os.getuid()
        self.acls_enforced = False
        # The mode bits of a file with an ACL contain the ACL_USER_OBJ, ACL_MASK, and ACL_OTHER
        # permissions, i.e., the group bits show the mask, not the ACL_GROUP_OBJ permissions.
        self.files = {
            '/allowed': (
                0o100640,
                pack_acl(
                    [
                        (ACL_USER_OBJ, ACL_READ | ACL_WRITE, ACL_UNDEFINED_ID),
                        (ACL_USER, ACL_READ, user_id),
                        (ACL_GROUP_OBJ, 0, ACL_UNDEFINED_ID),
                        (ACL_MASK, ACL_READ, ACL_UNDEFINED_ID),
                        (ACL_OTHER, 0, ACL_UNDEFINED_ID),
                    ]
                ),
            ),
            '/denied': (
                0o100644,
                pack_acl(
                    [
                        (ACL_USER_OBJ, ACL_READ | ACL_WRITE, ACL_UNDEFINED_ID),
                        (ACL_USER, 0, user_id),
                        (ACL_GROUP_OBJ, ACL_READ, ACL_UNDEFINED_ID),
                        (ACL_MASK, ACL_READ, ACL_UNDEFINED_ID),
                        (ACL_OTHER, ACL_READ, ACL_UNDEFINED_ID),
                    ]
                ),
            ),
        }

    def init_with_config(self, conn_info, config_3):
        self.acls_enforced = conn_info is not None and conn_info.is_wanted(mfusepy.FUSE_CAP_POSIX_ACL)

    def getattr(self, path, fh=None):
        if path == '/':
            return {'st_mode': 0o040755, 'st_nlink': 2, 'st_uid': os.getuid(), 'st_gid': os.getgid()}
        if path in self.files:
            # Owned by root so that the calling user is neither the owner nor in the owning group.
            return {
                'st_mode': self.files[path][0],
                'st_nlink': 1,
                'st_uid': 0,
                'st_gid': 0,
                'st_size': len(FILE_CONTENTS),
            }
        raise mfusepy.FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        return ['.', '..', *[name.lstrip('/') for name in self.files]]

    def listxattr(self, path):
        return [ACL_ACCESS_XATTR] if path in self.files else []

    def getxattr(self, path, name, position=0):
        if path in self.files and name == ACL_ACCESS_XATTR:
            return self.files[path][1]
        raise mfusepy.FuseOSError(mfusepy.ENOATTR)

    def open(self, path, flags):
        if path not in self.files:
            raise mfusepy.FuseOSError(errno.ENOENT)
        return 0

    def read(self, path, size, offset, fh):
        return FILE_CONTENTS[offset : offset + size]


class MountedACLFileSystem:
    def __init__(self, mount_point):
        self.timeout = 4
        self.mount_point = str(mount_point)
        self.operations = ACLFileSystem()
        self.thread = threading.Thread(
            target=mfusepy.FUSE, args=(self.operations, self.mount_point), kwargs={'foreground': True}
        )

    def __enter__(self):
        self.thread.start()
        t0 = time.time()
        while not os.path.ismount(self.mount_point):
            if time.time() - t0 > self.timeout:
                raise RuntimeError("Expected mount point but it isn't one!")
            time.sleep(0.1)
        return self.operations

    def __exit__(self, exception_type, exception_value, exception_traceback):
        subprocess.run(["fusermount", "-u", self.mount_point], check=True, capture_output=True)
        self.thread.join(self.timeout)


@pytest.mark.skipif(sys.platform != 'linux', reason="POSIX ACLs are only supported by the Linux FUSE driver.")
@pytest.mark.skipif(os.geteuid() == 0, reason="The root user is not subject to ACL permission checks.")
def test_posix_acl_enforcement(tmp_path):
    with MountedACLFileSystem(tmp_path) as operations:
        if not operations.acls_enforced:
            pytest.skip("The kernel or the loaded libfuse version does not support FUSE_CAP_POSIX_ACL.")

        # The ACLs are visible, e.g. for getfacl, even without FUSE_CAP_POSIX_ACL, but the kernel
        # returns them from its own ACL cache when it does enforce them, so also check them here.
        for name in ['allowed', 'denied']:
            assert os.getxattr(tmp_path / name, ACL_ACCESS_XATTR) == operations.files['/' + name][1]

        # Readable only because of the ACL. The mode bits deny access to everyone but the owner.
        with open(tmp_path / 'allowed', 'rb') as file:
            assert file.read() == FILE_CONTENTS

        # Not readable even though the mode bits would allow it because the ACL denies access.
        with pytest.raises(PermissionError), open(tmp_path / 'denied', 'rb') as file:
            file.read()
