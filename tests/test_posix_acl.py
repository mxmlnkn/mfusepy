#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import errno
import os
import stat
import struct
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402
from mfusepy import (  # noqa: E402
    XATTR_NAME_POSIX_ACL_ACCESS,
    ACLPermission,
    ACLTag,
    PosixACLEntry,
    posix_acl_from_xattr,
    posix_acl_to_xattr,
)

linux_only = pytest.mark.skipif(sys.platform != 'linux', reason="The POSIX ACL xattr format is Linux-specific.")


def _example_entries() -> list[PosixACLEntry]:
    # Same as: setfacl -m u::rw-,u:1000:r-x,g::---,m::r-x,o::--- <file>
    return [
        PosixACLEntry(ACLTag.USER_OBJ, ACLPermission.READ | ACLPermission.WRITE),
        PosixACLEntry(ACLTag.USER, ACLPermission.READ | ACLPermission.EXECUTE, 1000),
        PosixACLEntry(ACLTag.GROUP_OBJ, ACLPermission(0)),
        PosixACLEntry(ACLTag.MASK, ACLPermission.READ | ACLPermission.EXECUTE),
        PosixACLEntry(ACLTag.OTHER, ACLPermission(0)),
    ]


@linux_only
def test_posix_acl_to_xattr_matches_the_kernel_format():
    packed = posix_acl_to_xattr(_example_entries())

    # Fixed little-endian layout: a 4-byte version header followed by 8 bytes per entry.
    assert packed == bytes.fromhex(
        '02000000'  # a_version
        ' 0100 0600 ffffffff'  # ACLTag.USER_OBJ, READ | WRITE, ACL_UNDEFINED_ID
        ' 0200 0500 e8030000'  # ACLTag.USER, READ | EXECUTE, 1000
        ' 0400 0000 ffffffff'  # ACLTag.GROUP_OBJ, none, ACL_UNDEFINED_ID
        ' 1000 0500 ffffffff'  # ACLTag.MASK, READ | EXECUTE, ACL_UNDEFINED_ID
        ' 2000 0000 ffffffff'  # ACLTag.OTHER, none, ACL_UNDEFINED_ID
    )
    assert posix_acl_from_xattr(packed) == _example_entries()


def _pack_in_given_order(entries) -> bytes:
    'Pack without canonicalizing, to check what the kernel does with a wrong order.'
    return struct.pack('<I', mfusepy.POSIX_ACL_XATTR_VERSION) + b''.join(
        struct.pack('<HHI', entry.tag.value, entry.permissions, entry.qualifier) for entry in entries
    )


@linux_only
def test_posix_acl_to_xattr_sorts_into_canonical_order(tmp_path):
    canonical = [
        PosixACLEntry(ACLTag.USER_OBJ, ACLPermission.READ | ACLPermission.WRITE),
        PosixACLEntry(ACLTag.USER, ACLPermission.READ, 1000),
        PosixACLEntry(ACLTag.GROUP_OBJ, ACLPermission(0)),
        PosixACLEntry(ACLTag.MASK, ACLPermission.READ),
        PosixACLEntry(ACLTag.OTHER, ACLPermission(0)),
    ]
    shuffled = [canonical[index] for index in reversed(range(len(canonical)))]
    assert posix_acl_to_xattr(shuffled) == posix_acl_to_xattr(canonical)

    path = tmp_path / 'file'
    path.write_bytes(b'')
    os.chmod(path, 0o644)
    try:
        os.setxattr(path, XATTR_NAME_POSIX_ACL_ACCESS, posix_acl_to_xattr(canonical))
    except OSError as exception:
        if exception.errno in [errno.EOPNOTSUPP, errno.ENOTSUP, errno.EPERM]:
            pytest.skip(f"The file system for {tmp_path} does not support POSIX ACLs.")
        raise

    # Red: the kernel rejects the wrong tag order, i.e., posix_acl_valid() is what requires it.
    try:
        os.setxattr(path, XATTR_NAME_POSIX_ACL_ACCESS, _pack_in_given_order(shuffled))
    except OSError as exception:
        assert exception.errno == errno.EINVAL
    else:
        pytest.fail("The kernel accepted an ACL with the wrong tag order!")

    # Green: what posix_acl_to_xattr produces for the same order is accepted by the kernel.
    os.setxattr(path, XATTR_NAME_POSIX_ACL_ACCESS, posix_acl_to_xattr(shuffled))
    assert os.getxattr(path, XATTR_NAME_POSIX_ACL_ACCESS) == posix_acl_to_xattr(canonical)


@linux_only
def test_posix_acl_from_xattr_errors():
    with pytest.raises(ValueError, match='version'):
        posix_acl_from_xattr(b'\x03\0\0\0')
    with pytest.raises(ValueError, match='truncated'):
        posix_acl_from_xattr(b'\x02\0\0')
    with pytest.raises(ValueError, match='truncated'):
        posix_acl_from_xattr(posix_acl_to_xattr([]) + b'\0')


@linux_only
def test_posix_acl_is_understood_by_the_kernel(tmp_path):
    'Check the packed representation against the kernel instead of only against itself.'
    path = tmp_path / 'file'
    path.write_bytes(b'')
    os.chmod(path, 0o644)

    entries = [
        PosixACLEntry(ACLTag.USER_OBJ, ACLPermission.READ | ACLPermission.WRITE),
        PosixACLEntry(ACLTag.USER, ACLPermission.READ, os.getuid() + 1),
        PosixACLEntry(ACLTag.GROUP_OBJ, ACLPermission(0)),
        PosixACLEntry(ACLTag.MASK, ACLPermission.READ),
        PosixACLEntry(ACLTag.OTHER, ACLPermission(0)),
    ]
    try:
        os.setxattr(path, XATTR_NAME_POSIX_ACL_ACCESS, posix_acl_to_xattr(entries))
    except OSError as exception:
        if exception.errno in [errno.EOPNOTSUPP, errno.ENOTSUP, errno.EPERM]:
            pytest.skip(f"The file system for {tmp_path} does not support POSIX ACLs.")
        raise

    assert posix_acl_from_xattr(os.getxattr(path, XATTR_NAME_POSIX_ACL_ACCESS)) == entries
    # The kernel derives the mode bits from the ACL: owner from ACLTag.USER_OBJ, group from
    # ACLTag.MASK, other from ACLTag.OTHER. A misunderstood ACL would show up as other mode bits.
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640


def test_posix_acl_throws_on_other_platforms():
    if sys.platform == 'linux':
        pytest.skip("The POSIX ACL xattr format is defined on Linux, where the helpers must work.")

    with pytest.raises(NotImplementedError):
        posix_acl_to_xattr(_example_entries())
    with pytest.raises(NotImplementedError):
        posix_acl_from_xattr(b'\x02\0\0\0')
