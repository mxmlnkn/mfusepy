#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import ctypes
import errno
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402

requires_fuse_3 = pytest.mark.skipif(
    mfusepy.fuse_version_major < 3,
    reason="The moved libfuse 2 options are applied by init_fuse_3.",
)


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

    def failing_generic(self, path):
        raise RuntimeError("generic failure")

    def failing_negative_oserror(self, path):
        raise OSError(-1, "negative errno")


class ConfigOperations:
    use_ns = True

    def init(self, path):
        pass


class ConfigFUSE(mfusepy.FUSE):
    def __init__(self, options):
        self.operations = ConfigOperations()
        self._libfuse2_options_moved_into_libfuse3_config = options


class InitConfigOperations:
    def __init__(self):
        self.calls = []

    def init(self, path):
        self.calls.append('init')

    def init_with_config(self, conn, config):
        self.calls.append(('init_with_config', config.nullpath_ok))


class FalseyError(Exception):
    def __bool__(self):
        return False


class RaisingInitOperations:
    use_ns = True

    def init(self, path):
        raise FalseyError("init failed")


@requires_fuse_3
def test_nopath_false_keeps_default():
    fuse = ConfigFUSE({'nopath': False})
    config = mfusepy.fuse_config()
    mfusepy.FUSE.init_fuse_3(fuse, None, ctypes.pointer(config))
    assert config.nullpath_ok == 0


@requires_fuse_3
def test_nopath_true_sets_nullpath_ok():
    fuse = ConfigFUSE({'nopath': True})
    config = mfusepy.fuse_config()
    mfusepy.FUSE.init_fuse_3(fuse, None, ctypes.pointer(config))
    assert config.nullpath_ok != 0


@requires_fuse_3
def test_unsettable_moved_option_raises():
    fuse = ConfigFUSE({'not_a_config_option': True})
    with pytest.raises(RuntimeError, match="not_a_config_option"):
        mfusepy.FUSE.init_fuse_3(fuse, None, ctypes.pointer(mfusepy.fuse_config()))


def test_regular_runtime_error_returns_einval(monkeypatch):
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    assert fuse._wrapper("getattr", fuse.failing_generic, b'/file') == -errno.EINVAL
    assert fuse._FUSE__critical_exception is None


def test_negative_oserror_returns_einval(monkeypatch):
    monkeypatch.setattr(mfusepy, 'fuse_exit', lambda: None)
    fuse = FakeFUSE()
    assert fuse._wrapper("getattr", fuse.failing_negative_oserror, b'/file') == -errno.EINVAL
    assert fuse._FUSE__critical_exception is None


@requires_fuse_3
def test_init_with_config_prefers_config_callback_and_applies_nopath():
    operations = InitConfigOperations()
    fuse = object.__new__(mfusepy.FUSE)
    fuse.operations = operations
    fuse._libfuse2_options_moved_into_libfuse3_config = {'nopath': True}

    mfusepy.FUSE.init_fuse_3(fuse, None, ctypes.pointer(mfusepy.fuse_config()))

    assert operations.calls == [('init_with_config', 1)]


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
