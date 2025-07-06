#!/usr/bin/env python

import argparse
import errno
import logging
import os
import threading

import mfusepy as fuse


def with_root_path(func):
    def wrapper(self, path, *args, **kwargs):
        return func(self, self.root + path, *args, **kwargs)

    return wrapper


def static_with_root_path(func):
    def wrapper(self, path, *args, **kwargs):
        return func(self.root + path, *args, **kwargs)

    return wrapper


class Loopback(fuse.Operations):
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.rwlock = threading.Lock()

    @with_root_path
    def access(self, path, amode):
        if not os.access(path, amode):
            raise fuse.FuseOSError(errno.EACCES)

    chmod = static_with_root_path(os.chmod)
    chown = static_with_root_path(os.chown)

    @with_root_path
    def create(self, path, mode, fi=None):
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    @with_root_path
    def flush(self, path, fh):
        return os.fsync(fh)

    @with_root_path
    def fsync(self, path, datasync, fh):
        if datasync != 0:
            return os.fdatasync(fh)
        return os.fsync(fh)

    @fuse.log_callback
    @with_root_path
    def getattr(self, path, fh=None):
        st = os.lstat(path)
        return {
            key: getattr(st, key)
            for key in ('st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid')
        }

    @with_root_path
    def link(self, target, source):
        return os.link(self.root + source, target)

    mkdir = static_with_root_path(os.mkdir)
    mknod = static_with_root_path(os.mknod)
    open = static_with_root_path(os.open)

    @with_root_path
    def read(self, path, size, offset, fh):
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.read(fh, size)

    @with_root_path
    def readdir(self, path, fh):
        return ['.', '..', *os.listdir(path)]

    readlink = static_with_root_path(os.readlink)

    @with_root_path
    def release(self, path, fh):
        return os.close(fh)

    @with_root_path
    def rename(self, old, new):
        return os.rename(old, self.root + new)

    rmdir = static_with_root_path(os.rmdir)

    @with_root_path
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

    @with_root_path
    def symlink(self, target, source):
        return os.symlink(source, target)

    @with_root_path
    def truncate(self, path, length, fh=None):
        with open(path, 'r+') as f:
            f.truncate(length)

    unlink = static_with_root_path(os.unlink)
    utimens = static_with_root_path(os.utime)

    @fuse.log_callback
    @with_root_path
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
