#!/usr/bin/env python3
# pylint: disable=protected-access

import errno
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


class FakeFUSE(mfusepy.FUSE):
    'FUSE subclass whose callbacks raise, so that _wrapper can be tested without mounting.'

    def __init__(self, *args, **kwargs):
        # Deliberately do not call FUSE.__init__ because there is no mount to set up.
        self._FUSE__critical_exception = None

    def init_fuse_2(self, conn):
        raise OSError(errno.EACCES, "init failed")

    def init_fuse_3(self, conn, config):
        raise RuntimeError("init failed")

    def getattr_fuse_3(self, path, buf, fip):
        raise OSError(errno.ENOENT, "no such file")

    def failing_readlink(self, path):
        raise SystemExit("critical failure")


class FalseyError(Exception):
    def __bool__(self):
        return False


class RaisingInitOperations:
    use_ns = True

    def init(self, path):
        raise FalseyError("init failed")


def test_init_fuse_2_oserror_aborts(monkeypatch):
    # fuse_exit() must not be called for real because there is no FUSE session in this test.
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    # The wrapped method is named init_fuse_2, only the passed callback name identifies it as init.
    result = fuse._wrapper("init", fuse.init_fuse_2, None)
    assert isinstance(fuse._FUSE__critical_exception, OSError)
    assert result == 0


def test_init_fuse_3_exception_aborts(monkeypatch):
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    result = fuse._wrapper("init", fuse.init_fuse_3, None, None)
    assert isinstance(fuse._FUSE__critical_exception, RuntimeError)
    assert result == 0


def test_regular_callback_returns_errno(monkeypatch):
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    result = fuse._wrapper("getattr", fuse.getattr_fuse_3, b'/file', None, None)
    assert fuse._FUSE__critical_exception is None
    assert result == -errno.ENOENT


def test_later_critical_exception_does_not_overwrite_first(monkeypatch):
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    assert fuse._wrapper("init", fuse.init_fuse_2, None) == 0
    first_exception = fuse._FUSE__critical_exception
    assert isinstance(first_exception, OSError)
    assert fuse._wrapper("readlink", fuse.failing_readlink, b'/file') == -errno.EFAULT
    assert fuse._FUSE__critical_exception is first_exception


def test_falsey_critical_exception_is_raised(monkeypatch):
    def fake_fuse_main_real(argc, argv, fuse_ops_v, sizeof_fuse_ops, ctx_p):
        if mfusepy.fuse_version_major == 2:
            fuse_ops_v.contents.init(None)
        else:
            fuse_ops_v.contents.init(None, None)
        return 0

    monkeypatch.setattr(mfusepy, 'fuse_main_real', fake_fuse_main_real)
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    with pytest.raises(FalseyError):
        mfusepy.FUSE(RaisingInitOperations(), '/tmp/mfusepy-test-mount')
