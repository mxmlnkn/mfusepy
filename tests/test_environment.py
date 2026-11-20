#!/usr/bin/env python3
# pylint: disable=wrong-import-position

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


def test_expected_fuse_major():
    expected = os.environ.get('MFUSEPY_EXPECT_FUSE_MAJOR')
    if expected is None:
        pytest.skip("MFUSEPY_EXPECT_FUSE_MAJOR is not set.")
    assert mfusepy.fuse_version_major == int(expected)
