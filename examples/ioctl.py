#!/usr/bin/env python

import argparse
import collections
import ctypes
import errno
import logging
import stat
import struct
import time

from ioctl_opt import IOWR

import mfusepy as fuse


class Ioctl(fuse.Operations):
    '''
    Example filesystem based on memory.py to demonstrate ioctl().

    Usage::

        mkdir test

        python ioctl.py test
        touch test/test

        gcc -o ioctl_test ioctl.c
        ./ioctl_test 100 test/test
    '''

    def __init__(self):
        self.files = {}
        self.data = collections.defaultdict(bytes)
        self.fd = 0
        now = time.time()
        self.files['/'] = {
            'st_mode': (stat.S_IFDIR | 0o755),
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
            'st_nlink': 2,
        }

    def create(self, path, mode, fi=None):
        self.files[path] = {
            'st_mode': (stat.S_IFREG | mode),
            'st_nlink': 1,
            'st_size': 0,
            'st_ctime': time.time(),
            'st_mtime': time.time(),
            'st_atime': time.time(),
        }

        self.fd += 1
        return self.fd

    def getattr(self, path, fh=None):
        if path not in self.files:
            raise fuse.FuseOSError(errno.ENOENT)

        return self.files[path]

    def ioctl(self, path, cmd, arg, fh, flags, data):
        M_IOWR = IOWR(ord('M'), 1, ctypes.c_uint32)
        if cmd == M_IOWR:
            inbuf = ctypes.create_string_buffer(4)
            ctypes.memmove(inbuf, data, 4)
            data_in = struct.unpack('<I', inbuf)[0]
            data_out = data_in + 1
            outbuf = struct.pack('<I', data_out)
            ctypes.memmove(data, outbuf, 4)
        else:
            raise fuse.FuseOSError(errno.ENOTTY)
        return 0

    def open(self, path, flags):
        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        return self.data[path][offset : offset + size]

    def readdir(self, path, fh):
        return ['.', '..'] + [x[1:] for x in self.files if x != '/']


def cli(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)
    fuse.FUSE(Ioctl(), args.mount, foreground=True)


if __name__ == '__main__':
    cli()
