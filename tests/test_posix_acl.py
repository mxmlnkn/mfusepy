#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import errno
import os
import stat
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402
from mfusepy import (  # noqa: E402
    ACL_EXECUTE,
    ACL_GROUP_OBJ,
    ACL_MASK,
    ACL_OTHER,
    ACL_READ,
    ACL_UNDEFINED_ID,
    ACL_USER,
    ACL_USER_OBJ,
    ACL_WRITE,
    XATTR_NAME_POSIX_ACL_ACCESS,
    PosixACLEntry,
    pack_posix_acl,
    unpack_posix_acl,
)

FILE_CONTENTS = b'Hello ACL!\n'


def test_feature_flags():
    connection = mfusepy.fuse_conn_info()
    # FUSE_CAP_ATOMIC_O_TRUNC because all implementations define it with the same meaning, see
    # SUPPORTED_FEATURE_FLAGS, while e.g. FUSE_CAP_POSIX_ACL only exists on Linux and NetBSD.
    flag = mfusepy.FUSE_CAP_ATOMIC_O_TRUNC
    other_flag = mfusepy.FUSE_CAP_ASYNC_READ

    assert not connection.is_capable(flag)
    assert not connection.is_wanted(flag)
    # Requesting a feature that the kernel is not capable of must not change anything because
    # libfuse aborts the mount with EPROTO for unknown 'want' flags.
    assert not connection.set_feature_flag(flag)
    assert connection.want == 0

    if connection._has_extended_features:
        connection.capable_ext = flag | other_flag
    else:
        connection.capable = flag | other_flag

    assert connection.is_capable(flag)
    assert not connection.is_capable(flag | mfusepy.FUSE_CAP_DONT_MASK)
    # No requested feature is trivially supported and requesting none trivially succeeds.
    assert connection.is_capable(0)
    assert connection.is_wanted(0)
    assert connection.set_feature_flag(0)
    assert connection.want == 0

    assert connection.set_feature_flag(flag)
    assert connection.is_wanted(flag)
    assert not connection.is_wanted(other_flag)
    # 'want' must be kept in sync with 'want_ext' for libfuse < 3.17 and also for newer versions,
    # which only convert 'want' into 'want_ext' if exactly one of both has been changed.
    assert connection.want == flag
    if connection._has_extended_features:
        assert connection.want_ext == flag

    connection.unset_feature_flag(flag)
    assert not connection.is_wanted(flag)
    assert connection.want == 0
    if connection._has_extended_features:
        assert connection.want_ext == 0


def test_supported_feature_flags():
    # Every flag in the mask must be one of the known ones, or a name is missing above it.
    assert 'unknown' not in mfusepy.feature_flag_names(mfusepy.SUPPORTED_FEATURE_FLAGS)
    # No FUSE implementation ever defined the bits 2 and 22.
    assert not mfusepy.SUPPORTED_FEATURE_FLAGS & ((1 << 2) | (1 << 22))
    # This one is defined with the same meaning by all of them.
    assert mfusepy.SUPPORTED_FEATURE_FLAGS & mfusepy.FUSE_CAP_ATOMIC_O_TRUNC

    if sys.platform == 'darwin':
        # macFUSE uses the bits 23 to 31 for Apple-specific features and has no POSIX ACL support.
        assert not mfusepy.SUPPORTED_FEATURE_FLAGS & mfusepy.FUSE_CAP_PASSTHROUGH
        assert not mfusepy.SUPPORTED_FEATURE_FLAGS & mfusepy.FUSE_CAP_POSIX_ACL
    elif sys.platform == 'linux' and mfusepy.fuse_version_major == 3:
        assert mfusepy.SUPPORTED_FEATURE_FLAGS & mfusepy.FUSE_CAP_POSIX_ACL


def _flag_outside_the_supported_mask() -> int:
    'Return a flag that the loaded FUSE implementation does not define with the documented meaning.'
    for flag in [mfusepy.FUSE_CAP_PASSTHROUGH, mfusepy.FUSE_CAP_POSIX_ACL, mfusepy.FUSE_CAP_WRITEBACK_CACHE]:
        if not mfusepy.SUPPORTED_FEATURE_FLAGS & flag:
            return flag
    # libfuse skips bit 22 and WinFsp uses it for FSP_FUSE_CAP_READ_ONLY, i.e., it is never one of
    # the documented flags. Staying inside 32 bits keeps it announceable via 'capable' as well.
    return 1 << 22


def test_feature_flags_outside_the_supported_mask():
    flag = _flag_outside_the_supported_mask()
    connection = mfusepy.fuse_conn_info()

    # Pretend that everything is announced, which is what macFUSE does for its own features.
    connection.capable = 0xFFFF_FFFF
    if connection._has_extended_features:
        connection.capable_ext = 0xFFFF_FFFF_FFFF_FFFF

    assert connection.is_capable(flag)  # It is announced as capable ...
    assert not connection.set_feature_flag(flag)  # ... but still must not be requested by name.
    assert connection.want == 0
    if connection._has_extended_features:
        assert connection.want_ext == 0

    # Unsetting such a flag must not clear whatever feature that bit stands for here either.
    if flag < 1 << 32:
        connection.want = flag
        connection.unset_feature_flag(flag)
        assert connection.want == flag
    elif connection._has_extended_features:
        connection.want_ext = flag
        connection.unset_feature_flag(flag)
        assert connection.want_ext == flag

    # A flag that this implementation does define with the documented meaning still works.
    assert connection.set_feature_flag(mfusepy.FUSE_CAP_ATOMIC_O_TRUNC)
    assert connection.is_wanted(mfusepy.FUSE_CAP_ATOMIC_O_TRUNC)


def test_feature_flags_beyond_32_bits():
    connection = mfusepy.fuse_conn_info()

    if connection._has_extended_features:
        connection.capable_ext = mfusepy.FUSE_CAP_ALLOW_IDMAP
        assert connection.is_capable(mfusepy.FUSE_CAP_ALLOW_IDMAP)
        assert connection.set_feature_flag(mfusepy.FUSE_CAP_ALLOW_IDMAP)
        assert connection.is_wanted(mfusepy.FUSE_CAP_ALLOW_IDMAP)
        # The flag does not fit into the 32-bit 'want' member, which must be left alone instead of
        # being wrapped around into some other flag.
        assert connection.want_ext == mfusepy.FUSE_CAP_ALLOW_IDMAP
        assert connection.want == 0

        connection.unset_feature_flag(mfusepy.FUSE_CAP_ALLOW_IDMAP)
        assert connection.want_ext == 0
        assert connection.want == 0
    else:
        # libfuse older than 3.17 has no 'want_ext', so flags beyond bit 31 can never be capable
        # and still must not end up in the 32-bit 'want' member.
        connection.capable = 0xFFFF_FFFF
        assert not connection.is_capable(mfusepy.FUSE_CAP_ALLOW_IDMAP)
        assert not connection.set_feature_flag(mfusepy.FUSE_CAP_ALLOW_IDMAP)
        assert connection.want == 0


def test_feature_flag_names():
    assert mfusepy.feature_flag_names(mfusepy.FUSE_CAP_POSIX_ACL) == 'FUSE_CAP_POSIX_ACL'
    assert mfusepy.feature_flag_names(0) == 'no flags'
    assert mfusepy.feature_flag_names(mfusepy.FUSE_CAP_POSIX_ACL | mfusepy.FUSE_CAP_ASYNC_READ) == (
        'FUSE_CAP_ASYNC_READ | FUSE_CAP_POSIX_ACL'
    )

    # Bits without a name must still show up. Bit 60 should stay unused for a while, and bit 22 is
    # an example for a bit that libfuse skipped between HANDLE_KILLPRIV_V2 and CACHE_SYMLINKS.
    assert mfusepy.feature_flag_names(1 << 60) == 'unknown bit 60'
    assert mfusepy.feature_flag_names(mfusepy.FUSE_CAP_POSIX_ACL | (1 << 22) | (1 << 60)) == (
        'FUSE_CAP_POSIX_ACL | unknown bit 22 | unknown bit 60'
    )


def test_pack_posix_acl():
    # Same as: setfacl -m u::rw-,u:1000:r-x,g::---,m::r-x,o::--- <file>
    entries = [
        PosixACLEntry(ACL_USER_OBJ, ACL_READ | ACL_WRITE),
        PosixACLEntry(ACL_USER, ACL_READ | ACL_EXECUTE, 1000),
        PosixACLEntry(ACL_GROUP_OBJ, 0),
        PosixACLEntry(ACL_MASK, ACL_READ | ACL_EXECUTE),
        PosixACLEntry(ACL_OTHER, 0),
    ]
    packed = pack_posix_acl(entries)

    # Fixed little-endian layout: a 4 B version header followed by 8 B per entry.
    assert packed == bytes.fromhex(
        '02000000'  # version 2
        ' 0100 0600 ffffffff'  # ACL_USER_OBJ, ACL_READ | ACL_WRITE, ACL_UNDEFINED_ID
        ' 0200 0500 e8030000'  # ACL_USER, ACL_READ | ACL_EXECUTE, 1000
        ' 0400 0000 ffffffff'  # ACL_GROUP_OBJ, no permissions, ACL_UNDEFINED_ID
        ' 1000 0500 ffffffff'  # ACL_MASK, ACL_READ | ACL_EXECUTE, ACL_UNDEFINED_ID
        ' 2000 0000 ffffffff'  # ACL_OTHER, no permissions, ACL_UNDEFINED_ID
    )
    assert unpack_posix_acl(packed) == entries

    # Plain triples work as well and the qualifier may be given as -1 instead of ACL_UNDEFINED_ID.
    assert pack_posix_acl([(ACL_OTHER, ACL_READ, -1)]) == pack_posix_acl([(ACL_OTHER, ACL_READ, ACL_UNDEFINED_ID)])


def test_unpack_posix_acl_errors():
    with pytest.raises(ValueError, match='version'):
        unpack_posix_acl(b'\x03\0\0\0')
    with pytest.raises(ValueError, match='truncated'):
        unpack_posix_acl(b'\x02\0\0')
    with pytest.raises(ValueError, match='truncated'):
        unpack_posix_acl(pack_posix_acl([(ACL_OTHER, 0, -1)])[:-1])


@pytest.mark.skipif(sys.platform != 'linux', reason="POSIX ACLs are only stored in xattrs on Linux.")
def test_pack_posix_acl_is_understood_by_the_kernel(tmp_path):
    'Check the packed representation against the kernel instead of only against itself.'
    path = tmp_path / 'file'
    path.write_bytes(FILE_CONTENTS)
    os.chmod(path, 0o644)

    entries = [
        PosixACLEntry(ACL_USER_OBJ, ACL_READ | ACL_WRITE),
        PosixACLEntry(ACL_USER, ACL_READ, os.getuid() + 1),
        PosixACLEntry(ACL_GROUP_OBJ, 0),
        PosixACLEntry(ACL_MASK, ACL_READ),
        PosixACLEntry(ACL_OTHER, 0),
    ]
    try:
        os.setxattr(path, XATTR_NAME_POSIX_ACL_ACCESS, pack_posix_acl(entries))
    except OSError as exception:
        if exception.errno in [errno.EOPNOTSUPP, errno.ENOTSUP, errno.EPERM]:
            pytest.skip(f"The file system for {tmp_path} does not support POSIX ACLs.")
        raise

    assert unpack_posix_acl(os.getxattr(path, XATTR_NAME_POSIX_ACL_ACCESS)) == entries
    # The kernel derives the mode bits from the ACL: owner from ACL_USER_OBJ, group from ACL_MASK,
    # and other from ACL_OTHER, i.e., an accepted but misunderstood ACL would show up here.
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640


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
                pack_posix_acl(
                    [
                        PosixACLEntry(ACL_USER_OBJ, ACL_READ | ACL_WRITE),
                        PosixACLEntry(ACL_USER, ACL_READ, user_id),
                        PosixACLEntry(ACL_GROUP_OBJ, 0),
                        PosixACLEntry(ACL_MASK, ACL_READ),
                        PosixACLEntry(ACL_OTHER, 0),
                    ]
                ),
            ),
            '/denied': (
                0o100644,
                pack_posix_acl(
                    [
                        PosixACLEntry(ACL_USER_OBJ, ACL_READ | ACL_WRITE),
                        PosixACLEntry(ACL_USER, 0, user_id),
                        PosixACLEntry(ACL_GROUP_OBJ, ACL_READ),
                        PosixACLEntry(ACL_MASK, ACL_READ),
                        PosixACLEntry(ACL_OTHER, ACL_READ),
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
        return [XATTR_NAME_POSIX_ACL_ACCESS] if path in self.files else []

    def getxattr(self, path, name, position=0):
        if path in self.files and name == XATTR_NAME_POSIX_ACL_ACCESS:
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
            assert os.getxattr(tmp_path / name, XATTR_NAME_POSIX_ACL_ACCESS) == operations.files['/' + name][1]

        # Readable only because of the ACL. The mode bits deny access to everyone but the owner.
        with open(tmp_path / 'allowed', 'rb') as file:
            assert file.read() == FILE_CONTENTS

        # Not readable even though the mode bits would allow it because the ACL denies access.
        with pytest.raises(PermissionError), open(tmp_path / 'denied', 'rb') as file:
            file.read()
