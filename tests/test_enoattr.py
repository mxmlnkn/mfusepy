# pylint: disable=wrong-import-position

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


@pytest.mark.skipif(
    mfusepy.ENOATTR is None,
    reason="The platform defines neither ENOATTR nor ENODATA.",
)
def test_enoattr_is_not_none():
    assert mfusepy.ENOATTR is not None, "neither errno.ENOATTR nor errno.ENODATA is defined"
