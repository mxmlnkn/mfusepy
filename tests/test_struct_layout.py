import ctypes
import os
import pprint
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402
from struct_layout_utils import (  # noqa: E402
    StructSpec,
    build_checks,
    c_probe,
    compile_and_run,
    find_compiler,
    parse_c_output,
    python_layout,
)

pytestmark = pytest.mark.order(0)


KERNEL_STRUCTS = [('c_stat', 'stat'), ('c_statvfs', 'statvfs'), ('c_flock_t', 'flock')]
# Fields that are padding, have an unstable C name, or are optional libc extensions.
SKIP_MEMBERS = {
    'stat': {'reserved', 'st_birthtimespec'},
    # f_type is a glibc extension that Ubuntu 22.04 headers do not declare.
    'statvfs': {'f_type'},
}

FUSE_STRUCTS = ['fuse_context', 'fuse_conn_info', 'fuse_file_info', 'fuse_operations']
if (mfusepy.fuse_version_major, mfusepy.fuse_version_minor) >= (2, 9) and not mfusepy._librefuse:
    FUSE_STRUCTS += ['fuse_buf', 'fuse_bufvec']
if mfusepy.fuse_version_major == 3:
    FUSE_STRUCTS += ['fuse_config']


def struct_specs() -> list[StructSpec]:
    specs = [
        StructSpec(
            python_name=python_name,
            c_name=c_name,
            key=c_name,
            skip_members=tuple(SKIP_MEMBERS.get(c_name, ())),
        )
        for python_name, c_name in KERNEL_STRUCTS
    ]
    specs += [
        StructSpec(
            python_name=struct_name,
            c_name=struct_name,
            member_sizes=True,
            bitfields=struct_name == 'fuse_file_info',
        )
        for struct_name in FUSE_STRUCTS
    ]
    return specs


CHECKS = build_checks(mfusepy, struct_specs())
PY_INFOS = python_layout(CHECKS)
C_CHECKER = c_probe(('sys/stat.h', 'sys/statvfs.h', 'fcntl.h', 'fuse.h'), CHECKS)
print(C_CHECKER)


def build_cflags() -> list[str]:
    # Common include locations for different OSes
    include_paths = [
        '/usr/local/include/osxfuse/fuse',
        '/usr/local/include/macfuse/fuse',
        '/usr/include/libfuse',
        '/usr/gnu/include/fuse',
    ]
    if os.environ.get('FUSE_INCLUDE_DIR'):
        include_paths.insert(0, os.environ['FUSE_INCLUDE_DIR'])
    if mfusepy.fuse_version_major == 3:
        include_paths += ['/usr/local/include/fuse3', '/usr/include/fuse3']
    else:
        include_paths += ['/usr/local/include/fuse', '/usr/include/fuse']

    cflags = [
        f'-DFUSE_USE_VERSION={mfusepy.fuse_version_major}{mfusepy.fuse_version_minor}',
        '-D_FILE_OFFSET_BITS=64',
    ]
    # librefuse's fuse.h is in the default include path, do not pick up the headers of a libfuse package.
    if not mfusepy._librefuse:
        cflags += [f'-I{path}' for path in include_paths if os.path.exists(path)]

    # Add possible pkg-config flags if available. Prefer the pkg-config package matching the loaded library
    # because this system may have both libfuse 2 and libfuse 3 development headers installed.
    fuse_libraries = ("fuse3", "fuse") if mfusepy.fuse_version_major == 3 else ("fuse", "fuse3")
    for fuse_lib in () if mfusepy._librefuse else fuse_libraries:
        try:
            pkg_config_flags = subprocess.check_output(['pkg-config', '--cflags', fuse_lib], text=True).split()
            cflags.extend(pkg_config_flags)
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    return cflags


@pytest.fixture(scope='module')
def c_output():
    if os.name == 'nt':
        pytest.skip("C compiler check not implemented for Windows")

    compiler = find_compiler()
    if compiler is None:
        pytest.skip("No C compiler available to verify struct layouts.")

    print(f"FUSE version: {mfusepy.fuse_version_major}.{mfusepy.fuse_version_minor}")
    try:
        return compile_and_run(C_CHECKER, compiler=compiler, cflags=build_cflags(), verbose=True)
    except subprocess.CalledProcessError as error:
        raise AssertionError(f"Could not compile C program to verify sizes:\n{error.stderr}") from error


def test_struct_layout(c_output):
    c_infos = parse_c_output(c_output)
    pprint.pprint(c_infos)

    fail = False
    for key, python_value in PY_INFOS.items():
        if key.endswith(' bit'):
            continue
        if c_infos[key] == python_value:
            print(f"OK: {key} = {c_infos[key]}")
        else:
            print(f"Mismatch for {key}: C={c_infos[key]}, Python={python_value}")
            fail = True

    assert not fail, "Struct layout mismatch, see stdout output for details!"


def test_flock_is_a_structure():
    assert issubclass(mfusepy.c_flock_t, ctypes.Structure)
    assert mfusepy.c_flock_t._fields_
    assert ctypes.sizeof(mfusepy.c_flock_t) > ctypes.sizeof(ctypes.c_void_p)


def test_lock_callback_uses_flock_pointer():
    lock_field = next(field for field in mfusepy.fuse_operations._fields_ if field[0] == 'lock')
    lock_argtypes = getattr(lock_field[1], '_argtypes_', None)
    assert lock_argtypes is not None
    assert lock_argtypes[-1] == ctypes.POINTER(mfusepy.c_flock_t)


@pytest.mark.skipif(sys.byteorder != 'little', reason="Bit numbering in the C test assumes little endian.")
def test_file_info_bitfields(c_output):
    c_infos = parse_c_output(c_output)
    fail = False
    for key, python_bit in PY_INFOS.items():
        if not key.endswith(' bit'):
            continue
        if c_infos[key] == python_bit:
            print(f"OK: {key} = {c_infos[key]}")
        else:
            print(f"Mismatch for {key}: C={c_infos[key]}, Python={python_bit}")
            fail = True
    assert not fail, "Bitfield layout mismatch, see stdout output for details!"
