#!/usr/bin/env python3

import argparse
import errno
import logging
import stat as stat_module
import sys

import mfusepy as fuse

log = logging.getLogger("readdir with offset")


class ReaddirWithOffset(fuse.Operations):
    """
    Minimal filesystem showing usage of readdir with offsets.

    We create a directory with many files to ensure the buffer fills up,
    triggering multiple readdir calls with different offsets.
    """

    use_ns = True

    def __init__(self, readdir_call_limit=10):
        self._readdir_calls = 0
        # Create enough files to fill the readdir buffer. (In my tests the readdir buffer was ~10)
        self._file_count = 1000
        self._readdir_call_limit = readdir_call_limit

    def getattr(self, path, fh=None):
        self._readdir_calls = 0
        if path == '/':
            # Root directory
            st = {
                'st_mode': stat_module.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_size': 4096,
                'st_ctime': 0,
                'st_mtime': 0,
                'st_atime': 0,
            }
        elif path.strip('/').isdigit():
            # Regular file
            st = {
                'st_mode': stat_module.S_IFREG | 0o644,
                'st_nlink': 1,
                'st_size': 0,
                'st_ctime': 0,
                'st_mtime': 0,
                'st_atime': 0,
            }
        else:
            raise fuse.FuseOSError(errno.ENOENT)

        return st

    def readdir(self, path, fh):
        """
        Yield directory entries with incrementing offsets starting at 1.
        An offset of 0 should only be returned when the offsets should be ignored.
        """

        # After ~10 entries, warn about the old bug.
        self._readdir_calls += 1
        if self._readdir_calls >= self._readdir_call_limit * self._file_count:
            log.warning("If you see this message repeating, the FUSE wrapper bug is triggered!")
            sys.exit(1)

        log.debug("readdir called %s times for path=%s", self._readdir_calls, path)

        if path != '/':
            raise fuse.FuseOSError(errno.ENOENT)

        # Yield . and ..
        offset = 1
        yield ('.', {'st_mode': stat_module.S_IFDIR | 0o755}, offset)
        offset += 1
        yield ('..', {'st_mode': stat_module.S_IFDIR | 0o755}, offset)
        offset += 1

        # Yield many files to ensure buffer fills up
        for i in range(self._file_count):
            yield f'{i:04d}', {'st_mode': stat_module.S_IFREG | 0o644}, offset
            offset += 1


def cli(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)
    fuse.FUSE(ReaddirWithOffset(), args.mount, foreground=True)


if __name__ == '__main__':
    cli()
