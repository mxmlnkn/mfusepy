#!/usr/bin/env python3

import ctypes
import errno
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


class Operations:
    def __init__(self):
        self.calls = []

    def write_buf(self, path, buf, offset, fh):
        self.calls.append(('write_buf', path, buf, offset, fh))
        return 0

    def read_buf(self, path, bufpp, size, offset, fh):
        self.calls.append(('read_buf', path, bufpp, size, offset, fh))
        return 0

    def poll(self, path, fh, ph, reventsp):
        self.calls.append(('poll', path, fh, ph, reventsp))
        return 0

    def flock(self, path, fh, op):
        self.calls.append(('flock', path, fh, op))
        return 0

    def fallocate(self, path, mode, offset, size, fh):
        self.calls.append(('fallocate', path, mode, offset, size, fh))
        return 0

    def syncfs(self, path):
        self.calls.append(('syncfs', path))
        return 0


def make_fuse(raw_fi=False):
    operations = Operations()
    fuse = types.SimpleNamespace(encoding='utf-8', errors='surrogateescape', raw_fi=raw_fi, operations=operations)
    return fuse, operations


def make_fip(fh=42):
    return types.SimpleNamespace(contents=types.SimpleNamespace(fh=fh))


def test_write_buf_wrapper_translates_path_and_fh():
    fuse, operations = make_fuse()
    buf = object()
    assert mfusepy.FUSE.write_buf(fuse, b'/file', buf, 7, make_fip()) == 0  # type: ignore
    assert operations.calls == [('write_buf', '/file', buf, 7, 42)]


def test_read_buf_wrapper_translates_path_and_fh():
    fuse, operations = make_fuse()
    bufpp = object()
    assert mfusepy.FUSE.read_buf(fuse, b'/file', bufpp, 11, 7, make_fip()) == 0  # type: ignore
    assert operations.calls == [('read_buf', '/file', bufpp, 11, 7, 42)]


def test_poll_wrapper_translates_path_and_fh():
    fuse, operations = make_fuse()
    ph = object()
    reventsp = object()
    assert mfusepy.FUSE.poll(fuse, b'/file', make_fip(), ph, reventsp) == 0  # type: ignore
    assert operations.calls == [('poll', '/file', 42, ph, reventsp)]


def test_flock_wrapper_translates_path_and_fh():
    fuse, operations = make_fuse()
    assert mfusepy.FUSE.flock(fuse, b'/file', make_fip(), 3) == 0  # type: ignore
    assert operations.calls == [('flock', '/file', 42, 3)]


def test_fallocate_wrapper_translates_path_and_fh():
    fuse, operations = make_fuse()
    assert mfusepy.FUSE.fallocate(fuse, None, 1, 2, 3, make_fip()) == 0  # type: ignore
    assert operations.calls == [('fallocate', None, 1, 2, 3, 42)]


def test_syncfs_wrapper_translates_path():
    fuse, operations = make_fuse()
    assert mfusepy.FUSE.syncfs(fuse, b'/file') == 0  # type: ignore
    assert operations.calls == [('syncfs', '/file')]


def test_write_buf_wrapper_accepts_missing_path():
    fuse, operations = make_fuse()
    buf = object()
    assert mfusepy.FUSE.write_buf(fuse, None, buf, 7, make_fip()) == 0  # type: ignore
    assert operations.calls == [('write_buf', None, buf, 7, 42)]


def test_read_buf_wrapper_accepts_missing_path():
    fuse, operations = make_fuse()
    bufpp = object()
    assert mfusepy.FUSE.read_buf(fuse, None, bufpp, 11, 7, make_fip()) == 0  # type: ignore
    assert operations.calls == [('read_buf', None, bufpp, 11, 7, 42)]


def test_flock_wrapper_accepts_missing_path():
    fuse, operations = make_fuse()
    assert mfusepy.FUSE.flock(fuse, None, make_fip(), 3) == 0  # type: ignore
    assert operations.calls == [('flock', None, 42, 3)]


def test_read_rejects_oversized_result():
    fuse, _ = make_fuse()
    fuse.operations.read = lambda path, size, offset, fh: b'x' * (size + 1)
    buf = ctypes.create_string_buffer(4)

    with pytest.raises(mfusepy.FuseOSError) as exception:
        mfusepy.FUSE.read(fuse, b'/file', buf, 4, 0, make_fip())  # type: ignore

    assert exception.value.errno == errno.EIO
