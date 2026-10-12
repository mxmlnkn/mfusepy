#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402
from mfusepy import CAPABILITY_BITS, FuseCapability, fuse_conn_info  # noqa: E402


def get_declared_capabilities() -> list[tuple[FuseCapability, int]]:
    return sorted(CAPABILITY_BITS.items(), key=lambda item: item[1])


def _set_capable(connection: fuse_conn_info, flags: int) -> None:
    if mfusepy._HAS_WANT_EXT:
        connection.capable_ext = flags
    else:
        connection.capable = flags


def is_wanted(connection: fuse_conn_info, capability: FuseCapability) -> bool:
    '''Return whether the given capability is requested to be enabled in 'want'/'want_ext'.'''
    flag = CAPABILITY_BITS.get(capability)
    if flag is None:
        return False
    want = connection.want_ext if mfusepy._HAS_WANT_EXT else connection.want
    return (want & flag) == flag


def test_capability_map_is_sane():
    # The map must only contain capabilities of the cross-platform enum and each bit at most once.
    assert set(CAPABILITY_BITS) <= set(FuseCapability)
    assert len(set(CAPABILITY_BITS.values())) == len(CAPABILITY_BITS)


def test_enable_undeclared_capability():
    # Every implementation leaves out the capabilities of the others, e.g., macFUSE's or WinFsp's.
    undeclared = next(capability for capability in FuseCapability if capability not in CAPABILITY_BITS)
    connection = fuse_conn_info()
    _set_capable(connection, 0xFFFF_FFFF_FFFF_FFFF)

    assert not connection.is_capable(undeclared)
    assert not is_wanted(connection, undeclared)
    assert not connection.enable(undeclared)
    assert connection.want == 0
    connection.disable(undeclared)
    assert connection.want == 0


def test_enable_requires_capable():
    capability, flag = get_declared_capabilities()[0]
    connection = fuse_conn_info()

    # Nothing is capable by default and enabling must not change 'want' then.
    assert not connection.is_capable(capability)
    assert not connection.enable(capability)
    assert connection.want == 0

    # Advertising one capability must not make the others capable.
    _set_capable(connection, flag)
    assert connection.is_capable(capability)
    other, _ = next((c, f) for c, f in get_declared_capabilities() if f != flag)
    assert not connection.is_capable(other)
    assert not connection.enable(other)
    assert not is_wanted(connection, other)

    assert connection.enable(capability)
    assert is_wanted(connection, capability)
    assert connection.want & (flag & 0xFFFF_FFFF)
    if mfusepy._HAS_WANT_EXT:
        assert connection.want_ext & flag

    connection.disable(capability)
    assert not is_wanted(connection, capability)
    if mfusepy._HAS_WANT_EXT:
        assert not connection.want_ext & flag


def test_enable_high_bit_capability():
    high = [(capability, flag) for capability, flag in get_declared_capabilities() if flag >= 1 << 32]
    if not high:
        pytest.skip("Only libfuse 3 with 64-bit capabilities declares flags beyond bit 31.")

    capability, flag = high[0]
    connection = fuse_conn_info()
    _set_capable(connection, flag)

    assert connection.enable(capability)
    # Flags beyond bit 31 must only be set in 'want_ext' instead of being wrapped into 'want'.
    assert connection.want == 0
    assert connection.want_ext == flag

    connection.disable(capability)
    assert connection.want_ext == 0
