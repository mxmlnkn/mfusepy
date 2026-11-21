#!/usr/bin/env python3
# pylint: disable=protected-access

# pytype: disable=attribute-error

import ctypes
import os
import pickle
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


def freebsd_types():
    return mfusepy._FuseTypes(mfusepy._FuseContext(system='FreeBSD', machine='amd64', fuse_version=(3, 18, 3)))


def test_freebsd_dev_t_is_64_bit():
    types = freebsd_types()
    assert ctypes.sizeof(types.c_dev_t) == 8


def test_freebsd_st_gen_is_64_bit():
    types = freebsd_types()
    fields = dict(types.c_stat._fields_)
    assert ctypes.sizeof(fields['st_gen']) == 8


def test_i686_linux_layout_is_supported():
    types = mfusepy._FuseTypes(mfusepy._FuseContext(system='Linux', machine='i686', fuse_version=(3, 18, 3)))
    assert ctypes.sizeof(types.c_stat) > 0


def test_unknown_linux_machine_raises():
    with pytest.raises(NotImplementedError, match='s390x'):
        mfusepy._FuseTypes(mfusepy._FuseContext(system='Linux', machine='s390x', fuse_version=(3, 18, 3)))


def test_public_ctypes_types_are_picklable():
    for name in ('c_stat', 'fuse_file_info', 'fuse_conn_info', 'fuse_operations'):
        ctype = getattr(mfusepy, name)
        assert pickle.loads(pickle.dumps(ctype)) is ctype


def test_netbsd_getxattr_returns_int():
    types = mfusepy._FuseTypes(
        mfusepy._FuseContext(system='NetBSD', machine='amd64', fuse_version=(3, 10, 0), librefuse=True)
    )
    assert types.getxattr_t._restype_ is ctypes.c_int  # type: ignore[attr-defined]
