#!/usr/bin/env python3
# pylint: disable=protected-access

import ctypes
import os
import sys

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
