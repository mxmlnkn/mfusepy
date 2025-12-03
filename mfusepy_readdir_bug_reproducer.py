#!/usr/bin/env python3
"""
Minimal reproducer for mfusepy readdir offset bug.

This demonstrates the infinite loop bug in mfusepy where readdir ignores
the offset parameter, causing it to always restart iteration from the beginning.

To reproduce:
1. Install mfusepy: pip install mfusepy
2. Run this script: python3 mfusepy_readdir_bug_reproducer.py /tmp/test_mount
3. In another terminal: ls /tmp/test_mount
4. The ls command will hang (infinite loop)

The bug: mfusepy's _readdir method iterates over all items from operations.readdir
but ignores the 'offset' parameter passed by FUSE. When the buffer fills up,
FUSE calls readdir again with an offset to resume, but mfusepy sends the same
items again, causing an infinite loop.
"""

import errno
import os
import stat as stat_module
import sys

try:
    import mfusepy as fuse
except ImportError:
    print("Error: mfusepy not installed. Install with: pip install mfusepy")
    sys.exit(1)


class BuggyFS(fuse.Operations):
    """
    Minimal filesystem that exposes the mfusepy readdir offset bug.

    We create a directory with many files to ensure the buffer fills up,
    triggering multiple readdir calls with different offsets.
    """

    def __init__(self):
        self.readdir_calls = 0
        # Create enough files to fill the readdir buffer
        self.num_files = 1000

    def getattr(self, path, fh=None):
        """Return file attributes."""
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
        elif path.startswith('/file'):
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
        Yield directory entries with incrementing offsets.

        This is the CORRECT implementation - we yield entries with proper offsets.
        However, mfusepy's _readdir method will IGNORE these offsets and always
        restart iteration from the beginning, causing an infinite loop.
        """
        self.readdir_calls += 1
        print(f"[DEBUG] readdir called {self.readdir_calls} times for path={path}", file=sys.stderr)

        if path != '/':
            raise fuse.FuseOSError(errno.ENOENT)

        # Yield . and ..
        offset = 1
        yield ('.', {'st_mode': stat_module.S_IFDIR | 0o755}, offset)
        offset += 1
        yield ('..', {'st_mode': stat_module.S_IFDIR | 0o755}, offset)
        offset += 1

        # Yield many files to ensure buffer fills up
        for i in range(self.num_files):
            filename = f'file{i:04d}.txt'
            attrs = {'st_mode': stat_module.S_IFREG | 0o644}
            print(f"[DEBUG] Yielding {filename} with offset {offset}", file=sys.stderr)
            yield (filename, attrs, offset)
            offset += 1

            # After ~10 entries, warn about the bug
            if i == 10:
                print("\n[WARNING] If you see this message repeating, the bug is triggered!", file=sys.stderr)
                print("[WARNING] mfusepy is ignoring offsets and restarting from the beginning.\n", file=sys.stderr)

    def read(self, path, size, offset, fh):
        """Read file data (empty files)."""
        return b''

    def open(self, path, flags):
        """Open file."""
        return 0


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <mountpoint>")
        print(f"Example: {sys.argv[0]} /tmp/test_mount")
        sys.exit(1)

    mountpoint = sys.argv[1]

    # Create mountpoint if it doesn't exist
    os.makedirs(mountpoint, exist_ok=True)

    print(f"Mounting buggy filesystem at {mountpoint}")
    print(f"In another terminal, run: ls {mountpoint}")
    print("If the bug exists, 'ls' will hang in an infinite loop.")
    print("Watch stderr for repeated '[WARNING]' messages.\n")

    fs = BuggyFS()
    fuse.FUSE(fs, mountpoint, foreground=True, allow_other=False)


if __name__ == '__main__':
    main()
