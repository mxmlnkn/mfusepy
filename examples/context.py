#!/usr/bin/env python

import argparse
import errno
import logging
import stat
import time

import mfusepy


class Context(mfusepy.Operations):
    'Example filesystem to demonstrate fuse_get_context()'

    def getattr(self, path, fh=None):
        uid, gid, pid = mfusepy.fuse_get_context()
        if path == '/':
            st = {'st_mode': (stat.S_IFDIR | 0o755), 'st_nlink': 2}
        elif path == '/uid':
            size = len(f'{uid}\n')
            st = {'st_mode': (stat.S_IFREG | 0o444), 'st_size': size}
        elif path == '/gid':
            size = len(f'{gid}\n')
            st = {'st_mode': (stat.S_IFREG | 0o444), 'st_size': size}
        elif path == '/pid':
            size = len(f'{pid}\n')
            st = {'st_mode': (stat.S_IFREG | 0o444), 'st_size': size}
        else:
            raise mfusepy.FuseOSError(errno.ENOENT)
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = time.time()
        return st

    def read(self, path, size, offset, fh):
        uid, gid, pid = mfusepy.fuse_get_context()

        def encoded(x):
            return (f'{x}\n').encode()

        if path == '/uid':
            return encoded(uid)
        if path == '/gid':
            return encoded(gid)
        if path == '/pid':
            return encoded(pid)

        raise RuntimeError(f'unexpected path: {path!r}')

    def readdir(self, path, fh):
        return ['.', '..', 'uid', 'gid', 'pid']


def cli(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)
    mfusepy.FUSE(Context(), args.mount, foreground=True, ro=True)


if __name__ == '__main__':
    cli()
