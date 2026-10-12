#!/usr/bin/env python3
# pylint: disable=protected-access
# The members of ctypes structs are defined dynamically via '_fields_', which pylint cannot see.
# pylint: disable=no-member

import ctypes.util
import os
import subprocess
import sys
import threading
import time

import pytest

# FUSE_CAP_POSIX_ACL is only implemented by libfuse 3, which mfusepy only picks on Linux when
# libfuse 2 is not installed. Prefer fuse3 there unless the environment already picks a libfuse, and
# only if fuse3 exists, so that this cannot make 'import mfusepy' fail on the BSDs, which have no
# libfuse3. This has to happen before importing mfusepy, which loads the library at import time.
if (
    sys.platform == 'linux'
    and not os.environ.get('FUSE_LIBRARY_PATH')
    and not os.environ.get('FUSE_LIBRARY_NAME')
    and ctypes.util.find_library('fuse3')
):
    os.environ['FUSE_LIBRARY_NAME'] = 'fuse3'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../examples')))

from posix_acl import PosixACL  # noqa: E402

import mfusepy  # noqa: E402


class MountedPosixACL:
    def __init__(self, mount_point):
        self.timeout = 4
        self.mount_point = str(mount_point)
        self.operations = PosixACL()
        self.thread = threading.Thread(
            target=mfusepy.FUSE, args=(self.operations, self.mount_point), kwargs={'foreground': True}
        )
        self.thread.daemon = True

    def _wait_mounted(self) -> None:
        deadline = time.time() + self.timeout
        while not os.path.ismount(self.mount_point):
            if time.time() > deadline:
                raise RuntimeError(f"{self.mount_point} did not become a mount point!")
            time.sleep(0.1)

    def __enter__(self):
        self.thread.start()
        self._wait_mounted()
        return self.operations

    def __exit__(self, exception_type, exception_value, exception_traceback):
        try:
            self._wait_mounted()
            subprocess.run(['fusermount', '-u', self.mount_point], check=True, capture_output=True)
            deadline = time.time() + self.timeout
            while os.path.ismount(self.mount_point):
                if time.time() > deadline:
                    raise RuntimeError("Unmounting did not finish in time!")
                time.sleep(0.1)
        finally:
            self.thread.join(self.timeout)


@pytest.mark.skipif(sys.platform != 'linux', reason="POSIX ACLs are only supported by the Linux FUSE driver.")
@pytest.mark.skipif(mfusepy.fuse_version_major < 3, reason="FUSE_CAP_POSIX_ACL is only implemented by libfuse 3.")
@pytest.mark.skipif(os.geteuid() == 0, reason="The root user is not subject to ACL permission checks.")
def test_posix_acl_enforcement(tmp_path):
    '''
    The example only sets the FUSE_CAP_POSIX_ACL bit in 'want' and returns ACLs from 'getxattr'.
    Without any further mfusepy support, the kernel must then enforce those ACLs.
    '''
    with MountedPosixACL(tmp_path):
        # Readable only because of the ACL; the mode bits deny reading to everyone but the owner.
        with open(tmp_path / 'allowed', 'rb') as file:
            assert file.read() == b''

        # Not readable even though the mode bits would allow it because the ACL denies access.
        with pytest.raises(PermissionError), open(tmp_path / 'denied', 'rb') as file:
            file.read()
