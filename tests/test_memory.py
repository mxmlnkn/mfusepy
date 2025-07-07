# pylint: disable=wrong-import-position
# pylint: disable=protected-access

import io
import os
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../examples')))

from memory import cli as cli_memory  # noqa: E402
from memory_nullpath import cli as cli_memory_nullpath  # noqa: E402


class RunCLI:
    def __init__(self, cli, mount_point):
        self.timeout = 4
        self.mount_point = str(mount_point)
        self.args = [self.mount_point]
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

            problematicWords = ['[Warning]', '[Error]']
            if any(word in output or word in errors for word in problematicWords):
                print("===== stdout =====\n", output)
                print("===== stderr =====\n", errors)
                raise AssertionError("There were warnings or errors!")

        finally:
            self.unmount()
            self.thread.join(self.timeout)

    def get_stdout(self):
        oldPosition = sys.stdout.tell()
        try:
            sys.stdout.seek(0)
            return sys.stdout.read()
        finally:
            sys.stdout.seek(oldPosition)

    def get_stderr(self):
        oldPosition = sys.stderr.tell()
        try:
            sys.stderr.seek(0)
            return sys.stderr.read()
        finally:
            sys.stderr.seek(oldPosition)

    def wait_for_mount_point(self):
        t0 = time.time()
        while True:
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
                )
            time.sleep(0.1)

    def unmount(self):
        self.wait_for_mount_point()

        subprocess.run(["fusermount", "-u", self.mount_point], check=True, capture_output=True)

        t0 = time.time()
        while True:
            if not os.path.ismount(self.mount_point):
                break
            if time.time() - t0 > self.timeout:
                raise RuntimeError("Unmounting did not finish in time!")
            time.sleep(0.1)


@pytest.mark.parametrize('cli', [cli_memory, cli_memory_nullpath])
def test_memory_file_system(cli, tmpdir):
    mount_point = tmpdir
    with RunCLI(cli, mount_point):
        assert os.path.isdir(mount_point)
        assert not os.path.isdir(mount_point / "foo")

        path = mount_point / "foo"
        with open(path, 'wb') as file:
            assert file.write(b"bar") == 3

        assert os.path.exists(path)
        assert os.path.isfile(path)
        assert not os.path.isdir(path)

        with open(path, 'rb') as file:
            assert file.read() == b"bar"

        os.truncate(path, 2)
        with open(path, 'rb') as file:
            assert file.read() == b"ba"

        os.chmod(path, 0)
        assert os.stat(path).st_mode & 0o777 == 0
        os.chmod(path, 0o777)
        assert os.stat(path).st_mode & 0o777 == 0o777

        os.chown(path, 12345, 23456)
        assert os.stat(path).st_uid == 12345
        assert os.stat(path).st_gid == 23456

        assert not os.listxattr(path)
        os.setxattr(path, b"user.tag-test", b"FOO-RESULT")
        assert os.listxattr(path)
        assert os.getxattr(path, b"user.tag-test") == b"FOO-RESULT"
        os.removexattr(path, b"user.tag-test")
        assert not os.listxattr(path)

        os.utime(path, (1.5, 12.5))
        assert os.stat(path).st_atime == 1.5
        assert os.stat(path).st_mtime == 12.5

        os.utime(path, ns=(int(1.5e9), int(12.5e9)))
        assert os.stat(path).st_atime == 1.5
        assert os.stat(path).st_mtime == 12.5

        assert os.listdir(mount_point) == ["foo"]
        os.unlink(path)
        assert not os.path.exists(path)

        os.mkdir(path)
        assert os.path.exists(path)
        assert not os.path.isfile(path)
        assert os.path.isdir(path)

        assert os.listdir(mount_point) == ["foo"]
        assert os.listdir(path) == []

        os.rename(mount_point / "foo", mount_point / "bar")
        assert not os.path.exists(mount_point / "foo")
        assert os.path.exists(mount_point / "bar")

        os.symlink(mount_point / "bar", path)
        assert os.path.exists(path)
        # assert os.path.isfile(path)  # Does not have a follow_symlink argument but it seems to be True, see below.
        assert os.path.isdir(path)
        assert os.path.islink(path)
        assert os.readlink(path) == mount_point / "bar"

        os.rmdir(mount_point / "bar")
        assert not os.path.exists(mount_point / "bar")

        assert os.statvfs(mount_point).f_bsize == 512
        assert os.statvfs(mount_point).f_bavail == 2048
