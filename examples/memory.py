#!/usr/bin/env python3

import argparse
import collections
import errno
import logging
import stat
import time
from typing import Any, Dict

import mfusepy


class Memory(mfusepy.LoggingMixIn, mfusepy.Operations):
    'Example memory filesystem. Supports only one level of files.'

    def __init__(self):
        self.data = collections.defaultdict(bytes)
        self.fd = 0
        now = time.time()
        self.files: Dict[str, Dict[str, Any]] = { '/': {
            'st_mode': (stat.S_IFDIR | 0o755),
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
            'st_nlink': 2,
        }}

    def chmod(self, path, mode):
        self.files[path]['st_mode'] &= 0o770000
        self.files[path]['st_mode'] |= mode
        return 0

    def chown(self, path, uid, gid):
        self.files[path]['st_uid'] = uid
        self.files[path]['st_gid'] = gid

    def create(self, path, mode, flags=None):
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
            raise mfusepy.FuseOSError(errno.ENOENT)
        return self.files[path]

    def getxattr(self, path, name, position=0):
        attrs = self.files[path].get('attrs', {})

        try:
            return attrs[name]
        except KeyError:
            return ''

    def listxattr(self, path):
        attrs = self.files[path].get('attrs', {})
        return attrs.keys()

    def mkdir(self, path, mode):
        self.files[path] = {
            'st_mode': (stat.S_IFDIR | mode),
            'st_nlink': 2,
            'st_size': 0,
            'st_ctime': time.time(),
            'st_mtime': time.time(),
            'st_atime': time.time(),
        }

        self.files['/']['st_nlink'] += 1

    def open(self, path, flags):
        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        return self.data[path][offset : offset + size]

    def readdir(self, path, fh):
        return ['.', '..'] + [x[1:] for x in self.files if x != '/']

    def readlink(self, path):
        return self.data[path]

    def removexattr(self, path, name):
        attrs = self.files[path].get('attrs', {})

        try:
            del attrs[name]
        except KeyError:
            pass

    def rename(self, old, new):
        self.data[new] = self.data.pop(old)
        self.files[new] = self.files.pop(old)

    def rmdir(self, path):
        # with multiple level support, need to raise ENOTEMPTY if contains any files
        self.files.pop(path)
        self.files['/']['st_nlink'] -= 1

    def setxattr(self, path, name, value, options, position=0):
        # Ignore options
        attrs = self.files[path].setdefault('attrs', {})
        attrs[name] = value

    def statfs(self, path):
        return {'f_bsize': 512, 'f_blocks': 4096, 'f_bavail': 2048}

    def symlink(self, target, source):
        self.files[target] = {'st_mode': (stat.S_IFLNK | 0o777), 'st_nlink': 1, 'st_size': len(source)}

        self.data[target] = source

    def truncate(self, path, length, fh=None):
        # make sure extending the file fills in zero bytes
        self.data[path] = self.data[path][:length].ljust(length, '\x00'.encode('ascii'))
        self.files[path]['st_size'] = length

    def unlink(self, path):
        self.data.pop(path)
        self.files.pop(path)

    def utimens(self, path, times=None):
        now = time.time()
        atime, mtime = times if times else (now, now)
        self.files[path]['st_atime'] = atime
        self.files[path]['st_mtime'] = mtime

    def write(self, path, data, offset, fh):
        self.data[path] = (
            # make sure the data gets inserted at the right offset
            self.data[path][:offset].ljust(offset, '\x00'.encode('ascii'))
            + data
            # and only overwrites the bytes that data is replacing
            + self.data[path][offset + len(data) :]
        )
        self.files[path]['st_size'] = len(self.data[path])
        return len(data)


def cli(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)
    mfusepy.FUSE(Memory(), args.mount, foreground=True)


if __name__ == '__main__':
    cli()
