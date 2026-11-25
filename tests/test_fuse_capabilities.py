#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import ctypes
import dataclasses
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402
from mfusepy import _CAPABILITY_BITS, FuseCapability, fuse_conn_info  # noqa: E402

_HAS_WANT = any(field[0] == 'want' for field in fuse_conn_info._fields_)
requires_want = pytest.mark.skipif(
    not _HAS_WANT,
    reason="libfuse before 2.8 has no fuse_conn_info.want member.",
)


def test_enable_is_callable():
    assert callable(fuse_conn_info().enable_capability)


def get_declared_capabilities() -> list[tuple[FuseCapability, int]]:
    return sorted(_CAPABILITY_BITS.items(), key=lambda item: item[1])


def _set_capable(connection: fuse_conn_info, flags: int) -> None:
    if mfusepy._HAS_WANT_EXT:
        connection.capable_ext = flags
    else:
        connection.capable = flags


def is_wanted(connection: fuse_conn_info, capability: FuseCapability) -> bool:
    '''Return whether the given capability is requested to be enabled in 'want'/'want_ext'.'''
    flag = _CAPABILITY_BITS.get(capability)
    if flag is None:
        return False
    want = connection.want_ext if mfusepy._HAS_WANT_EXT else connection.want
    return (want & flag) == flag


def test_capability_map_is_sane():
    # The map must only contain capabilities of the cross-platform enum and each bit at most once.
    assert set(_CAPABILITY_BITS) <= set(FuseCapability)
    assert len(set(_CAPABILITY_BITS.values())) == len(_CAPABILITY_BITS)


def test_capability_map_is_private():
    assert fuse_conn_info._CAPABILITY_BITS is _CAPABILITY_BITS
    assert not hasattr(fuse_conn_info, 'CAPABILITY_BITS')


@requires_want
def test_enable_undeclared_capability():
    # Every implementation leaves out the capabilities of the others, e.g., macFUSE's or WinFsp's.
    undeclared = next(capability for capability in FuseCapability if capability not in _CAPABILITY_BITS)
    connection = fuse_conn_info()
    _set_capable(connection, 0xFFFF_FFFF_FFFF_FFFF)

    assert not connection.is_capable(undeclared)
    assert not is_wanted(connection, undeclared)
    assert not connection.enable_capability(undeclared)
    assert connection.want == 0
    connection.disable_capability(undeclared)
    assert connection.want == 0


@requires_want
def test_enable_requires_capable():
    capability, flag = get_declared_capabilities()[0]
    connection = fuse_conn_info()

    # Nothing is capable by default and enabling must not change 'want' then.
    assert not connection.is_capable(capability)
    assert not connection.enable_capability(capability)
    assert connection.want == 0

    # Advertising one capability must not make the others capable.
    _set_capable(connection, flag)
    assert connection.is_capable(capability)
    other, _ = next((c, f) for c, f in get_declared_capabilities() if f != flag)
    assert not connection.is_capable(other)
    assert not connection.enable_capability(other)
    assert not is_wanted(connection, other)

    assert connection.enable_capability(capability)
    assert is_wanted(connection, capability)
    assert connection.want & (flag & 0xFFFF_FFFF)
    if mfusepy._HAS_WANT_EXT:
        assert connection.want_ext & flag

    connection.disable_capability(capability)
    assert not is_wanted(connection, capability)
    if mfusepy._HAS_WANT_EXT:
        assert not connection.want_ext & flag


def test_feature_flag_helpers_are_typed_by_factory():
    context = mfusepy._context
    if not context.has_feature_flags or context.libfuse is None:
        pytest.skip("libfuse does not export the feature flag helpers.")

    # A second CDLL object has distinct ctypes function pointers. Their signatures must be configured by
    # _FuseTypes itself instead of relying on the module-level aliases of the runtime instance.
    libfuse = ctypes.CDLL(mfusepy._libfuse_path)
    types = mfusepy._FuseTypes(dataclasses.replace(context, libfuse=libfuse))
    conn_info = types.fuse_conn_info
    expected_argtypes = [ctypes.POINTER(conn_info), ctypes.c_uint64]

    assert conn_info._set_feature_flag.argtypes == expected_argtypes
    assert conn_info._set_feature_flag.restype is ctypes.c_bool
    assert conn_info._unset_feature_flag.argtypes == expected_argtypes
    assert conn_info._unset_feature_flag.restype is None
    assert conn_info._get_feature_flag.argtypes == expected_argtypes
    assert conn_info._get_feature_flag.restype is ctypes.c_bool


@requires_want
def test_enable_high_bit_capability():
    high = [(capability, flag) for capability, flag in get_declared_capabilities() if flag >= 1 << 32]
    if not high:
        pytest.skip("Only libfuse 3 with 64-bit capabilities declares flags beyond bit 31.")

    capability, flag = high[0]
    connection = fuse_conn_info()
    _set_capable(connection, flag)

    assert connection.enable_capability(capability)
    # Flags beyond bit 31 must only be set in 'want_ext' instead of being wrapped into 'want'.
    assert connection.want == 0
    assert connection.want_ext == flag

    connection.disable_capability(capability)
    assert connection.want_ext == 0
