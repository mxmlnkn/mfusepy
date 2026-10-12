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
import errno
import logging
import os

import mfusepy as fuse
from mfusepy import ACL_UNDEFINED_ID, ACLPermission, ACLTag, PosixACLEntry, posix_acl_to_xattr


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
        if conn_info.is_capable(fuse.FuseCapability.POSIX_ACL):
            conn_info.enable(fuse.FuseCapability.POSIX_ACL)

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
        return [fuse.XATTR_NAME_POSIX_ACL_ACCESS] if path in self.files else []

    @fuse.overrides(fuse.Operations)
    def getxattr(self, path, name, position=0):
        if path in self.files and name == fuse.XATTR_NAME_POSIX_ACL_ACCESS:
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
