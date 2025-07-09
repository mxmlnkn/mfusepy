#!/usr/bin/env python

import argparse
import errno
import logging
import os
import threading
from typing import Any, Dict, Optional

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
    use_ns = True

    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.rwlock = threading.Lock()

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def access(self, path: str, amode: int) -> int:
        if not os.access(path, amode):
            raise fuse.FuseOSError(errno.EACCES)
        return 0

    chmod = static_with_root_path(os.chmod)
    chown = static_with_root_path(os.chown)

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def create(self, path: str, mode: int, fi=None) -> int:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def flush(self, path: str, fh: int) -> int:
        os.fsync(fh)
        return 0

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def fsync(self, path: str, datasync: int, fh: int) -> int:
        if datasync != 0:
            os.fdatasync(fh)
        else:
            os.fsync(fh)
        return 0

    @fuse.log_callback
    @with_root_path
    @fuse.overrides(fuse.Operations)
    def getattr(self, path: str, fh: Optional[int] = None) -> Dict[str, Any]:
        st = os.lstat(path)
        return {
            key: getattr(st, key)
            for key in ('st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid')
        }

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def link(self, target: str, source: str):
        return os.link(self.root + source, target)

    mkdir = static_with_root_path(os.mkdir)
    mknod = static_with_root_path(os.mknod)
    open = static_with_root_path(os.open)

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.read(fh, size)

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def readdir(self, path: str, fh: int) -> fuse.ReadDirResult:
        return ['.', '..', *os.listdir(path)]

    readlink = static_with_root_path(os.readlink)

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def release(self, path: str, fh: int) -> int:
        os.close(fh)
        return 0

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def rename(self, old: str, new: str):
        return os.rename(old, self.root + new)

    rmdir = static_with_root_path(os.rmdir)

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def statfs(self, path: str) -> Dict[str, int]:
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
    @fuse.overrides(fuse.Operations)
    def symlink(self, target: str, source: str):
        return os.symlink(source, target)

    @with_root_path
    @fuse.overrides(fuse.Operations)
    def truncate(self, path: str, length: int, fh: Optional[int] = None) -> int:
        with open(path, 'rb+') as f:
            f.truncate(length)
        return 0

    unlink = static_with_root_path(os.unlink)
    utimens = static_with_root_path(os.utime)

    @fuse.log_callback
    @with_root_path
    @fuse.overrides(fuse.Operations)
    def write(self, path: str, data, offset: int, fh: int) -> int:
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
