#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import logging
import os
import stat
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402


class Operations:
    def readdir(self, path, fh):
        return [
            ('a', {'st_mode': stat.S_IFDIR | 0o755, 'st_ino': 1}, 0),
            ('b', {'st_ino': 2}, 0),
            ('c', {'st_mode': stat.S_IFREG | 0o644}, 0),
            'd',
        ]


def test_readdir_does_not_inherit_stat_values_between_entries():
    fuse = types.SimpleNamespace(encoding='utf-8', errors='surrogateescape', operations=Operations())
    fuse_file_info = types.SimpleNamespace(contents=types.SimpleNamespace(fh=0))
    entries = []

    def filler(buf, name, st, offset, *args):
        entries.append((name.decode(), None if st is None else (st.st_mode, st.st_ino)))
        return 0

    mfusepy.FUSE._readdir(fuse, b'/', None, filler, 0, fuse_file_info)  # type: ignore

    assert entries == [
        ('a', (stat.S_IFDIR | 0o755, 1)),
        ('b', (0, 2)),
        ('c', (stat.S_IFREG | 0o644, 0)),
        ('d', (0, 0)),
    ]


def run_readdir(items, filler_return=0):
    class Operations:
        def readdir(self, path, fh):
            return items

    fuse = types.SimpleNamespace(encoding='utf-8', errors='surrogateescape', operations=Operations())
    fuse_file_info = types.SimpleNamespace(contents=types.SimpleNamespace(fh=0))
    entries = []

    def filler(buf, name, st, offset, *args):
        entries.append((name.decode(), None if st is None else (st.st_mode, st.st_ino), offset))
        return filler_return

    mfusepy.FUSE._readdir(fuse, b'/', None, filler, 0, fuse_file_info)  # type: ignore
    return entries


def test_readdir_integer_and_none_attrs():
    entries = run_readdir([('a', stat.S_IFREG | 0o644, 0), ('b', None, 0)])
    assert entries == [('a', (stat.S_IFREG | 0o644, 0), 0), ('b', None, 0)]


def test_readdir_filler_early_termination():
    entries = run_readdir(
        [('a', {'st_mode': stat.S_IFREG | 0o644}, 0), ('b', {'st_mode': stat.S_IFDIR | 0o755}, 0)],
        filler_return=1,
    )
    assert entries == [('a', (stat.S_IFREG | 0o644, 0), 0)]


def test_readdir_nonzero_offset_warns(caplog):
    with caplog.at_level(logging.WARNING):
        entries = run_readdir([('a', {'st_mode': stat.S_IFREG | 0o644}, 5)])

    assert entries == [('a', (stat.S_IFREG | 0o644, 0), 0)]
    assert "non-zero offsets" in caplog.text
