# pylint: disable=wrong-import-position
# pylint: disable=protected-access

import ctypes
import errno
import fcntl
import io
import os
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Optional

import pytest
from ioctl_opt import IOWR

pwd: Optional[ModuleType]
try:
    import pwd as _pwd

    pwd = _pwd
except ImportError:
    pwd = None

grp: Optional[ModuleType]
try:
    import grp as _grp

    grp = _grp
except ImportError:
    grp = None

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../examples')))

from loopback import cli as cli_loopback  # noqa: E402
from memory import cli as cli_memory  # noqa: E402
from memory_nullpath import cli as cli_memory_nullpath  # noqa: E402
from readdir_returning_offsets import cli as cli_readdir_returning_offsets  # noqa: E402
from readdir_with_offset import cli as cli_readdir_with_offset  # noqa: E402

# Some Python interpreters, e.g. the macOS Python may lack os.*xattr APIs.
os_has_xattr_funcs = all(hasattr(os, f) for f in ("listxattr", "setxattr", "getxattr", "removexattr"))


def filter_platform_files(files):
    # macOS uses files starting with ._ (known as AppleDouble files) to store file metadata and
    # extended attributes when the underlying filesystem does not natively support macOS-specific features.
    #
    # Legacy macOS filesystems (HFS/HFS+) used a "dual-fork" structure:
    #
    # Data Fork: The actual content of the file (what most OSs see).
    # Resource Fork: Metadata like icons, window positions, and application-specific resources.
    # When you copy files to a filesystem that only supports a single data stream (like FAT32, SMB/network shares,
    # or some FUSE implementations), macOS cannot "attach" the metadata to the file. Instead, it creates a second,
    # hidden file with the ._ prefix to store that metadata.
    #
    # Common types of data found in these files include:
    #
    # Finder Info: Labels, tags, and whether the file should be hidden.
    # Extended Attributes (xattrs): Custom metadata used by applications (e.g., "Where from" URL for downloads).
    # Resource Forks: Legacy data used by older Mac apps.
    # ACLs: Access Control Lists for permissions.
    files = [f for f in files if not f.startswith("._")]
    return files


def get_mount_output() -> str:
    """Return the output of the system's 'mount' command as a string."""
    try:
        completed = subprocess.run(["mount"], capture_output=True, check=True, text=True)
        return completed.stdout
    except Exception as exc:
        return f"<Unable to run mount command>\n{exc}"


def stat_readable(st, path=None):
    """Return a single human-readable line from an os.stat_result."""
    user_name = None
    if pwd:
        try:
            user_name = pwd.getpwuid(st.st_uid).pw_name
        except Exception:
            pass
    group_name = None
    if grp:
        try:
            group_name = grp.getgrgid(st.st_gid).gr_name
        except Exception:
            pass

    mode = stat.filemode(st.st_mode)
    size = str(st.st_size)
    user = f"{user_name or st.st_uid}"
    group = f"{group_name or st.st_gid}"
    atime = datetime.fromtimestamp(st.st_atime).isoformat()
    ctime = datetime.fromtimestamp(st.st_ctime).isoformat()
    mtime = datetime.fromtimestamp(st.st_mtime).isoformat()
    dev = str(getattr(st, "st_dev", ""))
    inode = str(getattr(st, "st_ino", ""))
    nlink = str(getattr(st, "st_nlink", ""))

    return f"{mode} {nlink} {user} {group} {size} a:{atime} c:{ctime} m:{mtime} {dev} {inode} {path or ''}"


class RunCLI:
    def __init__(self, cli, mount_point, arguments):
        self.timeout = 4
        self.mount_point = str(mount_point)
        self.args = [*arguments, self.mount_point]
        self.thread = threading.Thread(target=cli, args=(self.args,))

        self._stdout = None
        self._stderr = None

    def __enter__(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

        self.thread.start()
        self.wait_for_mount_point()

        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        try:
            stdout = sys.stdout
            stderr = sys.stderr
            sys.stdout = self._stdout
            sys.stderr = self._stderr
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read()
            errors = stderr.read()

            problematic_words = ['[Warning]', '[Error]']
            if any(word in output or word in errors for word in problematic_words):
                print("===== stdout =====\n", output)
                print("===== stderr =====\n", errors)
                raise AssertionError("There were warnings or errors!")

        finally:
            self.unmount()
            self.thread.join(self.timeout)

    def get_stdout(self):
        old_position = sys.stdout.tell()
        try:
            sys.stdout.seek(0)
            return sys.stdout.read()
        finally:
            sys.stdout.seek(old_position)

    def get_stderr(self):
        old_position = sys.stderr.tell()
        try:
            sys.stderr.seek(0)
            return sys.stderr.read()
        finally:
            sys.stderr.seek(old_position)

    def wait_for_mount_point(self):
        t0 = time.time()
        while True:
            st = os.stat(self.mount_point)  # helps diagnose getattr issues
            if os.path.ismount(self.mount_point):
                break
            if time.time() - t0 > self.timeout:
                mount_list = "<Unable to run mount command>"
                try:
                    mount_list = subprocess.run("mount", capture_output=True, check=True).stdout.decode()
                except Exception as exception:
                    mount_list += f"\n{exception}"
                raise RuntimeError(
                    "Expected mount point but it isn't one!"
                    "\n===== stderr =====\n"
                    + self.get_stderr()
                    + "\n===== stdout =====\n"
                    + self.get_stdout()
                    + "\n===== mount =====\n"
                    + mount_list
                    + "\n===== stat(self.mount_point) =====\n"
                    + f"{stat_readable(st)}\n"
                )
            time.sleep(0.1)

    def unmount(self):
        self.wait_for_mount_point()

        # Linux: fusermount -u, macOS: umount, FreeBSD: umount
        cmd = ["fusermount", "-u", self.mount_point] if sys.platform == 'linux' else ["umount", self.mount_point]
        subprocess.run(cmd, check=True, capture_output=True)

        t0 = time.time()
        while True:
            if not os.path.ismount(self.mount_point):
                break
            if time.time() - t0 > self.timeout:
                raise RuntimeError("Unmounting did not finish in time!")
            time.sleep(0.1)


@pytest.mark.parametrize('cli', [cli_loopback, cli_memory, cli_memory_nullpath])
def test_read_write_file_system(cli, tmp_path):
    if cli == cli_loopback:
        mount_source = tmp_path / "folder"
        mount_point = tmp_path / "mounted"
        mount_source.mkdir()
        mount_point.mkdir()
        arguments = [str(mount_source)]
    else:
        mount_point = tmp_path
        arguments = []
    with RunCLI(cli, mount_point, arguments):
        st = os.stat(mount_point)
        assert os.path.isdir(mount_point), f"{mount_point} is not a directory, st={stat_readable(st)}!"

        path = mount_point / "foo"
        assert not path.is_dir()

        try:
            n = path.write_bytes(b"bar")
        except PermissionError:
            mtab = get_mount_output()
            pytest.fail(reason=f"PermissionError, mount_point: st={stat_readable(st)}, mtab:\n{mtab}")
        else:
            assert n == 3

        assert path.exists()
        assert path.is_file()
        assert not path.is_dir()

        assert path.read_bytes() == b"bar"

        # ioctl does not work for regular files on macOS / *BSD.
        # IOCTL(2) for BSDs and macOS:
        # [ENOTTY] The fd argument is not associated with a character special device.
        if sys.platform == 'linux' and cli == cli_memory:
            with open(path, 'rb') as file:
                # Test a simple ioctl command that returns the argument incremented by one.
                argument = 123
                iowr_m = IOWR(ord('M'), 1, ctypes.c_uint32)
                result = fcntl.ioctl(file, iowr_m, struct.pack('I', argument))
                assert struct.unpack('I', result)[0] == argument + 1

        os.truncate(path, 2)
        assert path.read_bytes() == b"ba"

        os.chmod(path, 0)
        assert os.stat(path).st_mode & 0o777 == 0
        os.chmod(path, 0o777)
        assert os.stat(path).st_mode & 0o777 == 0o777

        try:
            # Only works for memory file systems on Linux, but not on macOS.
            os.chown(path, 12345, 23456)
            assert os.stat(path).st_uid == 12345
            assert os.stat(path).st_gid == 23456
        except PermissionError:
            if sys.platform != 'darwin':
                assert cli == cli_loopback

        os.chown(path, os.getuid(), os.getgid())
        assert os.stat(path).st_uid == os.getuid()
        assert os.stat(path).st_gid == os.getgid()

        if os_has_xattr_funcs:
            try:
                assert not os.listxattr(path)
                os.setxattr(path, b"user.tag-test", b"FOO-RESULT")
                assert os.listxattr(path)
                assert os.getxattr(path, b"user.tag-test") == b"FOO-RESULT"
                os.removexattr(path, b"user.tag-test")
                assert not os.listxattr(path)
            except OSError as exception:
                assert cli == cli_loopback
                assert exception.errno == errno.ENOTSUP

        os.utime(path, (1.5, 12.5))
        assert os.stat(path).st_atime == 1.5
        assert os.stat(path).st_mtime == 12.5

        os.utime(path, ns=(int(1.5e9), int(12.5e9)))
        assert os.stat(path).st_atime == 1.5
        assert os.stat(path).st_mtime == 12.5

        assert filter_platform_files(os.listdir(mount_point)) == ["foo"]
        os.unlink(path)
        assert not path.exists()

        os.mkdir(path)
        assert path.exists()
        assert not path.is_file()
        assert path.is_dir()

        assert filter_platform_files(os.listdir(mount_point)) == ["foo"]
        assert os.listdir(path) == []

        os.rename(mount_point / "foo", mount_point / "bar")
        assert not os.path.exists(mount_point / "foo")
        assert os.path.exists(mount_point / "bar")

        os.symlink(mount_point / "bar", path)
        assert path.exists()
        # assert path.is_file()  # Does not have a follow_symlink argument but it seems to be True, see below.
        assert path.is_dir()
        assert os.path.islink(path)
        assert os.readlink(path) == str(mount_point / "bar")

        os.rmdir(mount_point / "bar")
        assert not os.path.exists(mount_point / "bar")

        if cli != cli_loopback:
            # Looks like macOS always returns the memory page size here (16K Apple Silicon, 4K Intel)
            # and not the value provided by the fuse fs implementation (here: 512).
            # FreeBSD returns 65536 (why?).
            if sys.platform == 'darwin':
                expected_bsize = os.sysconf('SC_PAGE_SIZE')
            elif sys.platform.startswith('freebsd'):
                expected_bsize = 65536
            else:
                expected_bsize = 512
            assert os.statvfs(mount_point).f_bsize == expected_bsize
            assert os.statvfs(mount_point).f_bavail == 2048

        for i in range(200):
            path = mount_point / str(i)
            assert not path.exists()
            assert path.write_bytes(b"bar") == 3
            assert len(filter_platform_files(os.listdir(mount_point))) == i + 2

        for i in range(200):
            path = mount_point / str(i)
            path.unlink()


@pytest.mark.parametrize('cli', [cli_memory_nullpath])
def test_use_inode(cli, tmp_path):
    mount_point = tmp_path
    arguments = []
    with RunCLI(cli, mount_point, arguments):
        st = os.stat(mount_point)
        assert os.path.isdir(mount_point), f"{mount_point} is not a directory, st={stat_readable(st)}!"

        assert os.stat(mount_point).st_ino == 31

        path = mount_point / "foo"
        assert not path.is_dir()

        try:
            n = path.write_bytes(b"bar")
        except PermissionError:
            mtab = get_mount_output()
            pytest.fail(reason=f"PermissionError, mount_point: st={stat_readable(st)}, mtab:\n{mtab}")
        else:
            assert n == 3

        assert path.exists()
        assert path.is_file()
        assert not path.is_dir()

        assert os.stat(path).st_ino == 100


@pytest.mark.parametrize('cli', [cli_readdir_with_offset, cli_readdir_returning_offsets])
def test_readdir_with_offset(cli, tmp_path):
    if sys.platform.startswith('openbsd') and cli == cli_readdir_with_offset:
        pytest.skip("OpenBSD FUSE implementation uses byte offsets, incompatible with this example's logic")
    mount_point = tmp_path
    arguments = []
    with RunCLI(cli, mount_point, arguments):
        assert os.path.isdir(mount_point)

        path = mount_point / "foo"
        assert not path.is_dir()

        assert len(set(filter_platform_files(os.listdir(mount_point)))) == 1000


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        # Directory argument must not be something in the current directory,
        # or else it might lead to recursive calls into FUSE.
        test_read_write_file_system(cli_memory_nullpath, Path(directory))
