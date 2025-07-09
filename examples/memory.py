#!/usr/bin/env python3

import argparse
import collections
import ctypes
import errno
import logging
import stat
import struct
import time
from typing import Any, Dict, Iterable, Optional, Tuple

import mfusepy as fuse


# Use log_callback instead of LoggingMixIn! This is only here for downwards compatibility tests.
class Memory(fuse.LoggingMixIn, fuse.Operations):
    'Example memory filesystem. Supports only one level of files.'

    use_ns = True

    def __init__(self) -> None:
        self.data: Dict[str, bytes] = collections.defaultdict(bytes)
        now = int(time.time() * 1e9)
        self.files: Dict[str, Dict[str, Any]] = {
            '/': {
                'st_mode': (stat.S_IFDIR | 0o755),
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now,
                'st_nlink': 2,
            }
        }

    @fuse.overrides(fuse.Operations)
    def chmod(self, path: str, mode: int) -> int:
        self.files[path]['st_mode'] &= 0o770000
        self.files[path]['st_mode'] |= mode
        return 0

    @fuse.overrides(fuse.Operations)
    def chown(self, path: str, uid: int, gid: int) -> int:
        self.files[path]['st_uid'] = uid
        self.files[path]['st_gid'] = gid
        return 0

    @fuse.overrides(fuse.Operations)
    def create(self, path: str, mode: int, fi=None) -> int:
        now = int(time.time() * 1e9)
        self.files[path] = {
            'st_mode': (stat.S_IFREG | mode),
            'st_nlink': 1,
            'st_size': 0,
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
        }
        return 0

    @fuse.overrides(fuse.Operations)
    def getattr(self, path: str, fh=None) -> Dict[str, Any]:
        if path not in self.files:
            raise fuse.FuseOSError(errno.ENOENT)
        return self.files[path]

    @fuse.overrides(fuse.Operations)
    def getxattr(self, path: str, name: str, position=0) -> bytes:
        attrs: Dict[str, bytes] = self.files[path].get('attrs', {})

        try:
            return attrs[name]
        except KeyError:
            return b''

    @fuse.overrides(fuse.Operations)
    def listxattr(self, path: str) -> Iterable[str]:
        attrs = self.files[path].get('attrs', {})
        return attrs.keys()

    @fuse.overrides(fuse.Operations)
    def mkdir(self, path: str, mode: int) -> int:
        now = int(time.time() * 1e9)
        self.files[path] = {
            'st_mode': (stat.S_IFDIR | mode),
            'st_nlink': 2,
            'st_size': 0,
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
        }

        self.files['/']['st_nlink'] += 1
        return 0

    @fuse.overrides(fuse.Operations)
    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        return self.data[path][offset : offset + size]

    @fuse.overrides(fuse.Operations)
    def readdir(self, path: str, fh) -> fuse.ReadDirResult:
        yield '.'
        yield '..'
        for x in self.files:
            if x.startswith(path) and len(x) > len(path):
                yield x[1:]

    @fuse.overrides(fuse.Operations)
    def readlink(self, path: str) -> str:
        return self.data[path].decode()

    @fuse.overrides(fuse.Operations)
    def removexattr(self, path: str, name: str) -> int:
        attrs: Dict[str, bytes] = self.files[path].get('attrs', {})

        try:
            del attrs[name]
        except KeyError:
            pass

        return 0

    @fuse.overrides(fuse.Operations)
    def rename(self, old: str, new: str) -> int:
        if old in self.data:  # Directories have no data.
            self.data[new] = self.data.pop(old)
        if old not in self.files:
            raise fuse.FuseOSError(errno.ENOENT)
        self.files[new] = self.files.pop(old)
        return 0

    @fuse.overrides(fuse.Operations)
    def rmdir(self, path: str) -> int:
        # with multiple level support, need to raise ENOTEMPTY if contains any files
        self.files.pop(path)
        self.files['/']['st_nlink'] -= 1
        return 0

    @fuse.overrides(fuse.Operations)
    def setxattr(self, path: str, name: str, value, options: int, position: int = 0) -> int:
        # Ignore options
        attrs: Dict[str, bytes] = self.files[path].setdefault('attrs', {})
        attrs[name] = value
        return 0

    @fuse.overrides(fuse.Operations)
    def statfs(self, path: str) -> Dict[str, int]:
        return {'f_bsize': 512, 'f_blocks': 4096, 'f_bavail': 2048}

    @fuse.overrides(fuse.Operations)
    def symlink(self, target: str, source: str) -> int:
        self.files[target] = {'st_mode': (stat.S_IFLNK | 0o777), 'st_nlink': 1, 'st_size': len(source)}
        self.data[target] = source.encode()
        return 0

    @fuse.overrides(fuse.Operations)
    def truncate(self, path: str, length: int, fh=None) -> int:
        # make sure extending the file fills in zero bytes
        self.data[path] = self.data[path][:length].ljust(length, '\x00'.encode('ascii'))
        self.files[path]['st_size'] = length
        return 0

    @fuse.overrides(fuse.Operations)
    def unlink(self, path: str) -> int:
        self.data.pop(path)
        self.files.pop(path)
        return 0

    @fuse.overrides(fuse.Operations)
    def utimens(self, path: str, times: Optional[Tuple[int, int]] = None) -> int:
        now = int(time.time() * 1e9)
        atime, mtime = times or (now, now)
        self.files[path]['st_atime'] = atime
        self.files[path]['st_mtime'] = mtime
        return 0

    @fuse.overrides(fuse.Operations)
    def write(self, path: str, data, offset: int, fh: int) -> int:
        self.data[path] = (
            # make sure the data gets inserted at the right offset
            self.data[path][:offset].ljust(offset, '\x00'.encode('ascii'))
            + data
            # and only overwrites the bytes that data is replacing
            + self.data[path][offset + len(data) :]
        )
        self.files[path]['st_size'] = len(self.data[path])
        return len(data)

    @fuse.overrides(fuse.Operations)
    def ioctl(self, path: str, cmd: int, arg, fh: int, flags: int, data) -> int:
        """
        An example ioctl implementation that defines a command with integer code corresponding to 'M' in ASCII,
        which returns the 32-bit integer argument incremented by 1.
        """
        from ioctl_opt import IOWR

        iowr_m = IOWR(ord('M'), 1, ctypes.c_uint32)
        if cmd == iowr_m:
            inbuf = ctypes.create_string_buffer(4)
            ctypes.memmove(inbuf, data, 4)
            data_in = struct.unpack('<I', inbuf)[0]
            data_out = data_in + 1
            outbuf = struct.pack('<I', data_out)
            ctypes.memmove(data, outbuf, 4)
        else:
            raise fuse.FuseOSError(errno.ENOTTY)
        return 0


def cli(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)
    fuse.FUSE(Memory(), args.mount, foreground=True)


if __name__ == '__main__':
    cli()
