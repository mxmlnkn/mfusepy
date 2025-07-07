#!/usr/bin/env python

import argparse
import errno
import logging
import os
import threading
from os.path import realpath

import mfusepy as fuse


class Loopback(fuse.LoggingMixIn, fuse.Operations):
    def __init__(self, root):
        self.root = realpath(root)
        self.rwlock = threading.Lock()

    def __call__(self, op, path, *args):
        return super().__call__(op, self.root + path, *args)

    def access(self, path, amode):
        if not os.access(path, amode):
            raise fuse.FuseOSError(errno.EACCES)

    chmod = os.chmod
    chown = os.chown

    def create(self, path, mode, fi=None):
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    def flush(self, path, fh):
        return os.fsync(fh)

    def fsync(self, path, datasync, fh):
        if datasync != 0:
            return os.fdatasync(fh)
        return os.fsync(fh)

    def getattr(self, path, fh=None):
        st = os.lstat(path)
        return {
            key: getattr(st, key)
            for key in ('st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid')
        }

    def link(self, target, source):
        return os.link(self.root + source, target)

    mkdir = os.mkdir
    mknod = os.mknod
    open = os.open

    def read(self, path, size, offset, fh):
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.read(fh, size)

    def readdir(self, path, fh):
        return ['.', '..', *os.listdir(path)]

    readlink = os.readlink

    def release(self, path, fh):
        return os.close(fh)

    def rename(self, old, new):
        return os.rename(old, self.root + new)

    rmdir = os.rmdir

    def statfs(self, path):
        stv = os.statvfs(path)
        return {
            key: getattr(stv, key)
            for key in (
                'f_bavail',
                'f_bfree',
                'f_blocks',
                'f_bsize',
                'f_favail',
                'f_ffree',
                'f_files',
                'f_flag',
                'f_frsize',
                'f_namemax',
            )
        }

    def symlink(self, target, source):
        return os.symlink(source, target)

    def truncate(self, path, length, fh=None):
        with open(path, 'r+') as f:
            f.truncate(length)

    unlink = os.unlink
    utimens = os.utime

    def write(self, path, data, offset, fh):
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.write(fh, data)


def cli(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('root')
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)
    fuse.FUSE(Loopback(args.root), args.mount, foreground=True)


if __name__ == '__main__':
    cli()
