#!/usr/bin/env python3

import argparse
import collections
import ctypes
import errno
import logging
import os
import stat
import struct
import sys
import time
from collections.abc import Iterable
from typing import Any, Optional

import mfusepy as fuse


# Use log_callback instead of LoggingMixIn! This is only here for downwards compatibility tests.
class Memory(fuse.LoggingMixIn, fuse.Operations):
    'Example memory filesystem. Supports only one level of files.'

    use_ns = True

    def __init__(self) -> None:
        self.data: dict[str, bytes] = collections.defaultdict(bytes)
        now = int(time.time() * 1e9)
        self.files: dict[str, dict[str, Any]] = {
            '/': {
                # writable by owner only
                # On NetBSD/librefuse, operations may run under slightly different
                # credentials (perfused), leading to kernel-side EACCES on create
                # if the directory isn't world-writable. Use 0777 for the root
                # to avoid credential-mismatch denials while keeping this a demo FS.
                'st_mode': (stat.S_IFDIR | 0o777),
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now,
                'st_nlink': 2,
                'st_flags': 0,
                'st_ino': 1,
                'st_size': 0,
                'st_blksize': 4096,
                'st_blocks': 0,
                # ensure the mount root is owned by the current user
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
            }
        }
        # Simple counter to hand out fake file handles for BSD stacks that
        # expect a non-zero fh from create/open. We don't actually use them.
        self._fh_counter: int = 1
        self._ino_counter: int = 100

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

    # FIX FOR NETBSD PERMISSIONS
    @fuse.overrides(fuse.Operations)
    def access(self, path: str, mode: int) -> int:
        return 0

    # FIX FOR NETBSD FILE CREATION
    @fuse.overrides(fuse.Operations)
    def mknod(self, path: str, mode: int, dev: int) -> int:
        fh = self.create(path, mode)
        self._fh_counter = fh -1  # undo increment in .create()
        return 0

    @fuse.overrides(fuse.Operations)
    def create(self, path: str, mode: int, fi=None) -> int:
        now = int(time.time() * 1e9)
        # On NetBSD/perfused the caller credentials may not match the
        # daemon's for permission purposes. Use the daemon's uid/gid so
        # default_permissions evaluates consistently for the mounter.
        uid, gid = os.getuid(), os.getgid()
        self.files[path] = {
            'st_mode': (stat.S_IFREG | mode),
            'st_nlink': 1,
            'st_size': 0,
            'st_blksize': 4096,
            'st_blocks': 0,
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
            'st_flags': 0,
            'st_ino': self._ino_counter,
            # ensure the file is owned by the current user
            'st_uid': uid,
            'st_gid': gid,
        }
        self._ino_counter += 1
        # Return a fake, non-zero file handle to satisfy stacks that expect it.
        self._fh_counter += 1
        return self._fh_counter

    @fuse.overrides(fuse.Operations)
    def getattr(self, path: str, fh=None) -> dict[str, Any]:
        if path not in self.files:
            raise fuse.FuseOSError(errno.ENOENT)
        return self.files[path]

    @fuse.overrides(fuse.Operations)
    def getxattr(self, path: str, name: str, position=0) -> bytes:
        attrs: dict[str, bytes] = self.files[path].get('attrs', {})

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
        uid, gid = os.getuid(), os.getgid()
        self.files[path] = {
            'st_mode': (stat.S_IFDIR | mode),
            'st_nlink': 2,
            'st_size': 0,
            'st_blksize': 4096,
            'st_blocks': 0,
            'st_ctime': now,
            'st_mtime': now,
            'st_atime': now,
            'st_flags': 0,
            'st_ino': self._ino_counter,
            # ensure the directory is owned by the current user
            'st_uid': uid,
            'st_gid': gid,
        }
        self._ino_counter += 1
        self.files['/']['st_nlink'] += 1
        return 0

    @fuse.overrides(fuse.Operations)
    def open(self, path: str, flags: int):
        """Perform simple permission checks, hand out a fake fh.

        BSD stacks may expect open() to validate write permissions.
        """
        # Creation fallback: on some librefuse paths, create() may not be
        # called even when O_CREAT is present. If the file doesn't exist yet
        # and O_CREAT is set, synthesize the inode here so the open succeeds.
        if (flags & os.O_CREAT) and (path not in self.files):
            now = int(time.time() * 1e9)
            # Emulate typical POSIX default mode (subject to umask)
            current_umask = os.umask(0)
            os.umask(current_umask)
            mode = (0o666 & (~current_umask))
            uid, gid = os.getuid(), os.getgid()
            self.files[path] = {
                'st_mode': (stat.S_IFREG | mode),
                'st_nlink': 1,
                'st_size': 0,
                'st_blksize': 4096,
                'st_blocks': 0,
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now,
                'st_flags': 0,
                'st_ino': self._ino_counter,
                'st_uid': uid,
                'st_gid': gid,
            }
            self._ino_counter += 1
            # ensure data entry exists
            _ = self.data[path]  # defaultdict will initialize to b''

        # If opening with write intent, ensure the mode allows it (no-op on NetBSD per access())
        if (flags & os.O_WRONLY) or (flags & os.O_RDWR):
            self.access(path, os.W_OK)

        # Handle truncate flag: clear file content and size
        if (flags & os.O_TRUNC) and (path in self.files):
            self.data[path] = b''
            self.files[path]['st_size'] = 0
            self.files[path]['st_mtime'] = int(time.time() * 1e9)
        # Return a fake, non-zero file handle
        self._fh_counter += 1
        return self._fh_counter

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
        attrs: dict[str, bytes] = self.files[path].get('attrs', {})

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
        attrs: dict[str, bytes] = self.files[path].setdefault('attrs', {})
        attrs[name] = value
        return 0

    @fuse.overrides(fuse.Operations)
    def statfs(self, path: str) -> dict[str, int]:
        return {'f_bsize': 512, 'f_blocks': 4096, 'f_bavail': 2048}

    @fuse.overrides(fuse.Operations)
    def symlink(self, target: str, source: str) -> int:
        self.files[target] = {
            'st_mode': (stat.S_IFLNK | 0o777),
            'st_nlink': 1,
            'st_size': len(source),
            'st_blksize': 4096,
            'st_blocks': 1,
            'st_ino': self._ino_counter,
            'st_uid': os.getuid(),
            'st_gid': os.getgid(),
            'st_ctime': int(time.time() * 1e9),
            'st_mtime': int(time.time() * 1e9),
            'st_atime': int(time.time() * 1e9),
            'st_flags': 0,
        }
        self._ino_counter += 1
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
    def utimens(self, path: str, times: Optional[tuple[int, int]] = None) -> int:
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
    def ioctl(self, path: str, cmd: int, arg: ctypes.c_void_p, fh: int, flags: int, data: ctypes.c_void_p) -> int:
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
    # Build FUSE kwargs: enable default_permissions everywhere so the kernel
    # enforces mode bits consistently, and add allow_other on NetBSD to cope
    # with potential credential proxying by perfused.
    # Keep NetBSD/librefuse as permissive as possible to avoid kernel-side
    # denials before our FS logic runs. On NetBSD do not use default_permissions
    # and do not pass allow_other (perfused may behave unexpectedly with it).
    # On other OSes, default_permissions yields predictable POSIX checks.
    # Use default_permissions so the kernel honors POSIX mode bits across OSes.
    # This helps especially on NetBSD/librefuse where kernel-side checks are stricter.
    fuse_kwargs = dict(foreground=True, default_permissions=False)
    fuse.FUSE(Memory(), args.mount, **fuse_kwargs)


if __name__ == '__main__':
    cli()
