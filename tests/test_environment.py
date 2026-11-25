#!/usr/bin/env python3
# pylint: disable=protected-access,wrong-import-position

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


def _mock_netbsd_runtime(monkeypatch, libraries):
    requested = []

    def fake_find_library(name):
        requested.append(name)
        return libraries.get(name)

    def fake_cdll(path):
        return SimpleNamespace(_name=path)

    monkeypatch.setattr(mfusepy.platform, 'system', lambda: 'NetBSD')
    monkeypatch.setattr(mfusepy.platform, 'machine', lambda: 'amd64')
    monkeypatch.setattr(mfusepy, 'find_library', fake_find_library)
    monkeypatch.setattr(mfusepy.ctypes, 'CDLL', fake_cdll)
    monkeypatch.setattr(mfusepy, 'get_fuse_version', lambda _: (2, 9))
    monkeypatch.setattr(mfusepy, '_get_fuse_version_patch', lambda _: None)
    monkeypatch.delenv('FUSE_LIBRARY_PATH', raising=False)
    return requested


def test_netbsd_honors_fuse_library_name(monkeypatch):
    requested = _mock_netbsd_runtime(monkeypatch, {'fuse3': '/fake/libfuse3.so'})
    monkeypatch.setenv('FUSE_LIBRARY_NAME', 'fuse3')

    context = mfusepy._FuseContext.from_runtime()

    assert context.libfuse._name == '/fake/libfuse3.so'
    assert requested == ['fuse3']


def test_netbsd_falls_back_to_librefuse_soname(monkeypatch):
    requested = _mock_netbsd_runtime(monkeypatch, {})
    monkeypatch.delenv('FUSE_LIBRARY_NAME', raising=False)

    context = mfusepy._FuseContext.from_runtime()

    assert context.libfuse._name == 'librefuse.so.2'
    assert requested == ['refuse']


def test_expected_fuse_major():
    expected = os.environ.get('MFUSEPY_EXPECT_FUSE_MAJOR')
    if expected is None:
        pytest.skip("MFUSEPY_EXPECT_FUSE_MAJOR is not set.")
    assert mfusepy.fuse_version_major == int(expected)
