#!/usr/bin/env python

import argparse
import errno
import logging
from typing import Optional

import paramiko

import mfusepy as fuse


class SFTP(fuse.Operations):
    '''
    A simple SFTP filesystem. Requires paramiko: http://www.lag.net/paramiko/

    You need to be able to login to remote host without entering a password.
    '''

    def __init__(self, host, username=None, port=22):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.load_system_host_keys()
        self.client.connect(host, port=port, username=username)
        self.sftp = self.client.open_sftp()

    @fuse.overrides(fuse.Operations)
    def chmod(self, path: str, mode: int) -> int:
        return self.sftp.chmod(path, mode)

    @fuse.overrides(fuse.Operations)
    def chown(self, path: str, uid: int, gid: int) -> int:
        return self.sftp.chown(path, uid, gid)

    @fuse.overrides(fuse.Operations)
    def create(self, path: str, mode, fi=None) -> int:
        f = self.sftp.open(path, 'w')
        f.chmod(mode)
        f.close()
        return 0

    @fuse.overrides(fuse.Operations)
    def destroy(self, path: str) -> None:
        self.sftp.close()
        self.client.close()

    @fuse.overrides(fuse.Operations)
    def getattr(self, path: str, fh: Optional[int] = None):
        try:
            st = self.sftp.lstat(path)
        except OSError:
            raise fuse.FuseOSError(errno.ENOENT)

        return {key: getattr(st, key) for key in ('st_atime', 'st_gid', 'st_mode', 'st_mtime', 'st_size', 'st_uid')}

    @fuse.overrides(fuse.Operations)
    def mkdir(self, path: str, mode: int) -> int:
        return self.sftp.mkdir(path, mode)

    @fuse.overrides(fuse.Operations)
    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        f = self.sftp.open(path)
        f.seek(offset, 0)
        buf = f.read(size)
        f.close()
        return buf

    @fuse.overrides(fuse.Operations)
    def readdir(self, path: str, fh: int) -> fuse.ReadDirResult:
        return ['.', '..'] + [name.encode('utf-8') for name in self.sftp.listdir(path)]

    @fuse.overrides(fuse.Operations)
    def readlink(self, path: str) -> str:
        return self.sftp.readlink(path)

    @fuse.overrides(fuse.Operations)
    def rename(self, old: str, new: str) -> int:
        return self.sftp.rename(old, new)

    @fuse.overrides(fuse.Operations)
    def rmdir(self, path: str) -> int:
        return self.sftp.rmdir(path)

    @fuse.overrides(fuse.Operations)
    def symlink(self, target: str, source: str) -> int:
        return self.sftp.symlink(source, target)

    @fuse.overrides(fuse.Operations)
    def truncate(self, path: str, length: int, fh: Optional[int] = None) -> int:
        return self.sftp.truncate(path, length)

    @fuse.overrides(fuse.Operations)
    def unlink(self, path: str) -> int:
        return self.sftp.unlink(path)

    @fuse.overrides(fuse.Operations)
    def utimens(self, path: str, times: Optional[tuple[int, int]] = None) -> int:
        return self.sftp.utime(path, times)

    @fuse.overrides(fuse.Operations)
    def write(self, path: str, data: bytes, offset: int, fh: int) -> int:
        f = self.sftp.open(path, 'r+')
        f.seek(offset, 0)
        f.write(data)
        f.close()
        return len(data)


def cli(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', dest='login')
    parser.add_argument('host')
    parser.add_argument('mount')
    args = parser.parse_args(args)

    logging.basicConfig(level=logging.DEBUG)

    if not args.login:
        if '@' in args.host:
            args.login, _, args.host = args.host.partition('@')

    fuse.FUSE(SFTP(args.host, username=args.login), args.mount, foreground=True, nothreads=True)


if __name__ == '__main__':
    cli()
