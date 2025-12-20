# pylint: disable=wrong-import-position

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


def test_enoattr_is_not_none():
    assert mfusepy.ENOATTR is not None, "neither errno.ENOATTR nor errno.ENODATA is defined"
