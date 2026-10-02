#!/usr/bin/env python3
# pylint: disable=protected-access

import errno
import os
import sys

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


def test_init_fuse_2_oserror_aborts(monkeypatch):
    # fuse_exit() must not be called for real because there is no FUSE session in this test.
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    # The wrapped method is named init_fuse_2, only the passed callback name identifies it as init.
    result = fuse._wrapper("init", fuse.init_fuse_2, None)
    assert isinstance(fuse._FUSE__critical_exception, OSError)
    assert result == -errno.EFAULT


def test_init_fuse_3_exception_aborts(monkeypatch):
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    result = fuse._wrapper("init", fuse.init_fuse_3, None, None)
    assert isinstance(fuse._FUSE__critical_exception, RuntimeError)
    assert result == -errno.EFAULT


def test_regular_callback_returns_errno(monkeypatch):
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    result = fuse._wrapper("getattr", fuse.getattr_fuse_3, b'/file', None, None)
    assert fuse._FUSE__critical_exception is None
    assert result == -errno.ENOENT
