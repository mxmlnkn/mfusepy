#!/usr/bin/env python3

import argparse
import collections
import errno
import os
import stat
import time
from collections.abc import Iterable
from typing import Any, Optional

import mfusepy as fuse


class Memory(fuse.Operations):
    'Example memory filesystem. Supports only one level of files.'

    flag_nullpath_ok = True
    flag_nopath = True
    use_ns = True

    def __init__(self) -> None:
        self.data: dict[str, bytes] = collections.defaultdict(bytes)
        self.fd = 0
        now = int(time.time() * 1e9)
        self.files: dict[str, dict[str, Any]] = {
            '/': {
                # writable by owner only
                'st_mode': (stat.S_IFDIR | 0o755),
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now,
                'st_nlink': 2,
                'st_ino': 31,
                # ensure the mount root is owned by the current user
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
            }
        }
        self._inode = 100
        self._opened: dict[int, str] = {}

    @fuse.overrides(fuse.Operations)
    def init_with_config(self, conn_info: Optional[fuse.fuse_conn_info], config_3: Optional[fuse.fuse_config]) -> None:
        # This only works for FUSE 3 while the flag_nullpath_ok and flag_nopath class members work for FUSE 2 and 3!
        if config_3:
            config_3.nullpath_ok = True
            config_3.use_ino = True

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
        uid, gid, _pid = fuse.fuse_get_context()
        self.files[path] = {
            'st_mode': (stat.S_IFREG | mode),
            'st_nlink': 1,
            'st_size': 0,
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
            'st_ino': self._inode,
            # ensure the file is owned by the current user
            'st_uid': uid,
            'st_gid': gid,
        }
        self._inode += 1

        self.fd += 1
        self._opened[self.fd] = path
        return self.fd

    @fuse.overrides(fuse.Operations)
    def getattr(self, path: str, fh=None) -> dict[str, Any]:
        if fh is not None and fh in self._opened:
            path = self._opened[fh]
        if path not in self.files:
            raise fuse.FuseOSError(errno.ENOENT)
        return self.files[path]

    @fuse.overrides(fuse.Operations)
    def getxattr(self, path: str, name: str, position: int = 0) -> bytes:
        attrs: dict[str, bytes] = self.files[path].get('attrs', {})

        try:
            return attrs[name]
        except KeyError:
            raise fuse.FuseOSError(fuse.ENOATTR)

    @fuse.overrides(fuse.Operations)
    def listxattr(self, path: str) -> Iterable[str]:
        attrs = self.files[path].get('attrs', {})
        return attrs.keys()

    @fuse.overrides(fuse.Operations)
    def mkdir(self, path: str, mode: int) -> int:
        now = int(time.time() * 1e9)
        uid, gid, _pid = fuse.fuse_get_context()
        self.files[path] = {
            'st_mode': (stat.S_IFDIR | mode),
            'st_nlink': 2,
            'st_size': 0,
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
            'st_ino': self._inode,
            # ensure the directory is owned by the current user
            'st_uid': uid,
            'st_gid': gid,
        }
        self._inode += 1

        self.files['/']['st_nlink'] += 1
        return 0

    @fuse.overrides(fuse.Operations)
    def open(self, path: str, flags: int) -> int:
        self.fd += 1
        self._opened[self.fd] = path
        return self.fd

    @fuse.overrides(fuse.Operations)
    def read(self, path: str, size, offset: int, fh: int) -> bytes:
        return self.data[self._opened[fh]][offset : offset + size]

    @fuse.overrides(fuse.Operations)
    def release(self, path: str, fh: int) -> int:
        del self._opened[fh]
        return 0

    @fuse.overrides(fuse.Operations)
    def opendir(self, path: str) -> int:
        self.fd += 1
        self._opened[self.fd] = path
        return self.fd

    @fuse.overrides(fuse.Operations)
    def readdir(self, path: str, fh: int) -> fuse.ReadDirResult:
        path = self._opened[fh]
        return [('.', self.files['/'], 0), ('..', self.files['/'], 0)] + [
            (x[1:], info, 0) for x, info in self.files.items() if x.startswith(path) and len(x) > len(path)
        ]

    @fuse.overrides(fuse.Operations)
    def releasedir(self, path: str, fh: int) -> int:
        del self._opened[fh]
        return 0

    @fuse.overrides(fuse.Operations)
    def readlink(self, path: str) -> str:
        return self.data[path].decode()

    @fuse.overrides(fuse.Operations)
    def removexattr(self, path: str, name: str) -> int:
        attrs: dict[str, bytes] = self.files[path].get('attrs', {})

        try:
            del attrs[name]
        except KeyError:
            raise fuse.FuseOSError(fuse.ENOATTR)

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
    def setxattr(self, path: str, name: str, value: bytes, options, position: int = 0) -> int:
        # Ignore options
        attrs: dict[str, bytes] = self.files[path].setdefault('attrs', {})
        attrs[name] = value
        return 0

    @fuse.overrides(fuse.Operations)
    def statfs(self, path: str) -> dict[str, int]:
        return {'f_bsize': 512, 'f_blocks': 4096, 'f_bavail': 2048}

    @fuse.overrides(fuse.Operations)
    def symlink(self, target: str, source: str) -> int:
        self.files[target] = {'st_mode': (stat.S_IFLNK | 0o777), 'st_nlink': 1, 'st_size': len(source)}
        self.data[target] = source.encode()
        return 0

    @fuse.overrides(fuse.Operations)
    def truncate(self, path: str, length: int, fh=None) -> int:
        if fh is not None and fh in self._opened:
            path = self._opened[fh]
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
    def utimens(self, path: str, times: Optional[tuple[int, int]] = None) -> int:
        now = int(time.time() * 1e9)
        atime, mtime = times or (now, now)
        self.files[path]['st_atime'] = atime
        self.files[path]['st_mtime'] = mtime
        return 0

    @fuse.overrides(fuse.Operations)
    def mknod(self, path: str, mode: int, dev: int) -> int:
        # OpenBSD calls mknod + open instead of create.
        now = int(time.time() * 1e9)
        uid, gid, _pid = fuse.fuse_get_context()
        self.files[path] = {
            'st_mode': mode,
            'st_nlink': 1,
            'st_size': 0,
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
            'st_ino': self._inode,
            # ensure the file is owned by the current user
            'st_uid': uid,
            'st_gid': gid,
        }
        self._inode += 1
        return 0

    @fuse.overrides(fuse.Operations)
    def write(self, path: str, data, offset: int, fh: int) -> int:
        path = self._opened[fh]
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

    fuse.FUSE(Memory(), args.mount, foreground=True, use_ino=True)


if __name__ == '__main__':
    cli()
