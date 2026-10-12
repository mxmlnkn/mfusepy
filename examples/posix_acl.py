#!/usr/bin/env python3
'''
Minimal example showing how to enable ACL enforcement.

On Linux, the kernel enforces POSIX ACLs for a FUSE file system if two things are done:

 1. 'getxattr' returns the ACL for 'system.posix_acl_access' in the binary format of
    <linux/posix_acl_xattr.h>, which is what 'posix_acl_to_xattr' below does.
 2. 'init_with_config' requests the FUSE_CAP_POSIX_ACL capability by setting its bit in
    'conn_info.want', which is the only place a feature is requested.

Without (2), the ACLs are still visible, e.g., to getfacl, but the kernel decides access with the
mode bits returned by 'getattr' instead of the ACL.
'''

import argparse
import enum
import errno
import logging
import os
import struct
from typing import NamedTuple

import mfusepy as fuse

# https://github.com/libfuse/libfuse/blob/master/include/fuse_common.h
FUSE_CAP_POSIX_ACL = 1 << 19

# POSIX ACLs are exchanged with the Linux kernel as extended attributes with these keys:
# https://github.com/torvalds/linux/blob/v7.2/include/uapi/linux/xattr.h#L91
XATTR_NAME_POSIX_ACL_ACCESS = 'system.posix_acl_access'
XATTR_NAME_POSIX_ACL_DEFAULT = 'system.posix_acl_default'

# https://github.com/torvalds/linux/blob/v7.2/include/uapi/linux/posix_acl_xattr.h
POSIX_ACL_XATTR_VERSION = 0x0002
# Qualifier of PosixACLEntry for tags that do not have one, defined as -1 in the kernel but converted to uint32_t.
ACL_UNDEFINED_ID = 0xFFFF_FFFF


# https://github.com/torvalds/linux/blob/v7.2/include/uapi/linux/posix_acl.h
class ACLTag(enum.Enum):
    'What the permissions of an ACL entry applies to.'

    # fmt: off
    USER_OBJ  = 0x01   # The usual non-ACL owning user
    USER      = 0x02
    GROUP_OBJ = 0x04   # The usual non-ACL owning group
    GROUP     = 0x08
    MASK      = 0x10
    OTHER     = 0x20
    # fmt: on


class ACLPermission(enum.IntFlag):
    'Permissions of an ACL entry, a combination of READ, WRITE, and EXECUTE.'

    # fmt: off
    READ    = 0x04
    WRITE   = 0x02
    EXECUTE = 0x01
    # fmt: on


class PosixACLEntry(NamedTuple):
    tag: ACLTag
    permissions: ACLPermission
    qualifier: int = ACL_UNDEFINED_ID  # uid for ACLTag.USER, gid for ACLTag.GROUP, else undefined


# struct posix_acl_xattr_header { __le32 a_version; }
_POSIX_ACL_XATTR_HEADER = struct.Struct('<I')
# struct posix_acl_xattr_entry { __le16 e_tag; __le16 e_perm; __le32 e_id; }
_POSIX_ACL_XATTR_ENTRY = struct.Struct('<HHI')


def posix_acl_to_xattr(entries: list[PosixACLEntry]) -> bytes:
    'Pack (tag, permissions, qualifier) triples into the Linux-specific system.posix_acl_access binary format.'
    # https://github.com/torvalds/linux/blob/v7.2/fs/posix_acl.c#L840-L876
    # The entries are sorted into the canonical order required by the kernel's posix_acl_valid() in
    # https://github.com/torvalds/linux/blob/v7.2/fs/posix_acl.c#L243 via a state machine.
    # The order is: USER_OBJ -> USER -> GROUP_OBJ -> GROUP -> MASK -> OTHER (the same order as their enum values)
    # See https://man7.org/linux/man-pages/man5/acl.5.html#VALID_ACLs
    ordered = sorted(entries, key=lambda entry: entry.tag.value)
    return _POSIX_ACL_XATTR_HEADER.pack(POSIX_ACL_XATTR_VERSION) + b''.join(
        # In case qualifier is -1, which the kernel allows in its interface, bit mask to 32-bit to avoid struct.error.
        _POSIX_ACL_XATTR_ENTRY.pack(entry.tag.value, entry.permissions, entry.qualifier & 0xFFFF_FFFF)
        for entry in ordered
    )


class PosixACL(fuse.Operations):
    '''
    A read-only file system with two root-owned files whose access can only be decided correctly if
    the kernel enforces the returned POSIX ACLs:

      - /allowed is not readable according to its mode bits, but its ACL grants the current user read access.
      - /denied is readable according to its mode bits, but its ACL denies the current user.
    '''

    use_ns = True

    def __init__(self) -> None:
        self.files = {
            '/allowed': (
                0o100640,  # ACL_USER_OBJ rw, ACL_MASK read, ACL_OTHER none
                posix_acl_to_xattr(
                    [
                        PosixACLEntry(ACLTag.USER_OBJ, ACLPermission.READ | ACLPermission.WRITE, ACL_UNDEFINED_ID),
                        PosixACLEntry(ACLTag.USER, ACLPermission.READ, os.getuid()),
                        PosixACLEntry(ACLTag.GROUP_OBJ, ACLPermission(0), ACL_UNDEFINED_ID),
                        PosixACLEntry(ACLTag.MASK, ACLPermission.READ, ACL_UNDEFINED_ID),
                        PosixACLEntry(ACLTag.OTHER, ACLPermission(0), ACL_UNDEFINED_ID),
                    ]
                ),
            ),
            '/denied': (
                0o100644,  # ACL_USER_OBJ rw, ACL_MASK read, ACL_OTHER read
                posix_acl_to_xattr(
                    [
                        PosixACLEntry(ACLTag.USER_OBJ, ACLPermission.READ | ACLPermission.WRITE, ACL_UNDEFINED_ID),
                        PosixACLEntry(ACLTag.USER, ACLPermission(0), os.getuid()),
                        PosixACLEntry(ACLTag.GROUP_OBJ, ACLPermission.READ, ACL_UNDEFINED_ID),
                        PosixACLEntry(ACLTag.MASK, ACLPermission.READ, ACL_UNDEFINED_ID),
                        PosixACLEntry(ACLTag.OTHER, ACLPermission.READ, ACL_UNDEFINED_ID),
                    ]
                ),
            ),
        }

    @fuse.overrides(fuse.Operations)
    def init_with_config(self, conn_info, config_3) -> None:
        # The only thing needed to make the kernel enforce POSIX ACLs: request the capability.
        # 'want' is the field for libfuse 2 and libfuse 3 converts it into 'want_ext'.
        if getattr(conn_info, 'capable_ext', conn_info.capable) & FUSE_CAP_POSIX_ACL:
            conn_info.want |= FUSE_CAP_POSIX_ACL

    @fuse.overrides(fuse.Operations)
    def getattr(self, path, fh=None):
        if path == '/':
            return {'st_mode': 0o040755, 'st_nlink': 2, 'st_uid': os.getuid(), 'st_gid': os.getgid()}
        if path in self.files:
            return {'st_mode': self.files[path][0], 'st_nlink': 1, 'st_uid': 0, 'st_gid': 0, 'st_size': 0}
        raise fuse.FuseOSError(errno.ENOENT)

    @fuse.overrides(fuse.Operations)
    def readdir(self, path, fh):
        return ['.', '..', *[name.lstrip('/') for name in self.files]]

    @fuse.overrides(fuse.Operations)
    def listxattr(self, path):
        return [XATTR_NAME_POSIX_ACL_ACCESS] if path in self.files else []

    @fuse.overrides(fuse.Operations)
    def getxattr(self, path, name, position=0):
        if path in self.files and name == XATTR_NAME_POSIX_ACL_ACCESS:
            return self.files[path][1]
        raise fuse.FuseOSError(fuse.ENOATTR)

    @fuse.overrides(fuse.Operations)
    def open(self, path, flags):
        if path not in self.files:
            raise fuse.FuseOSError(errno.ENOENT)
        return 0

    @fuse.overrides(fuse.Operations)
    def read(self, path, size, offset, fh):
        return b''


def cli(args=None):
    parser = argparse.ArgumentParser(description='Mount a tiny file system whose files have POSIX ACLs.')
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)
    fuse.FUSE(PosixACL(), args.mount, foreground=True)


if __name__ == '__main__':
    cli()
