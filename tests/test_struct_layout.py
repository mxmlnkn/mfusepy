import ctypes
import os
import platform
import pprint
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mfusepy  # noqa: E402

pytestmark = pytest.mark.order(0)


# Only check the struct members that are present on all supported platforms.
STRUCT_NAMES = {
    'stat': [
        'st_atimespec',
        'st_blksize',
        'st_blocks',
        'st_ctimespec',
        'st_dev',
        'st_gid',
        'st_ino',
        'st_mode',
        'st_mtimespec',
        'st_nlink',
        'st_rdev',
        'st_size',
        'st_uid',
    ],
    'statvfs': [
        'f_bavail',
        'f_bfree',
        'f_blocks',
        'f_bsize',
        'f_favail',
        'f_ffree',
        'f_files',
        'f_flag',
        'f_frsize',
        'f_fsid',
        'f_namemax',
    ],
    'fuse_context': ['fuse', 'uid', 'gid', 'pid', 'umask'],
    'fuse_conn_info': [
        'proto_major',
        'proto_minor',
        'max_write',
        'max_readahead',
        'capable',
        'want',
        'max_background',
        'congestion_threshold',
    ],
    'fuse_operations': [
        'getattr',
        'readlink',
        'mknod',
        'mkdir',
        'unlink',
        'rmdir',
        'symlink',
        'rename',
        'link',
        'chmod',
        'chown',
        'truncate',
        'open',
        'read',
        'write',
        'statfs',
        'flush',
        'release',
        'fsync',
        'setxattr',
        'getxattr',
        'listxattr',
        'removexattr',
    ],
}

STRUCT_NAMES['fuse_file_info'] = ['flags', 'fh', 'lock_owner']

if (mfusepy.fuse_version_major, mfusepy.fuse_version_minor) >= (2, 9) and not mfusepy._librefuse:
    STRUCT_NAMES['fuse_buf'] = ['size', 'flags', 'mem', 'fd', 'pos']
    if mfusepy._FUSE_VERSION >= (3, 17, 1):
        STRUCT_NAMES['fuse_buf'] += ['mem_size']
    STRUCT_NAMES['fuse_bufvec'] = ['count', 'idx', 'off', 'buf']

if mfusepy._FUSE_VERSION >= (3, 19, 0) and not mfusepy._librefuse:
    STRUCT_NAMES['fuse_operations'] += ['syncfs']

_system = platform.system()
if _system == 'Linux':
    if mfusepy._machine.startswith('mips') and ctypes.sizeof(ctypes.c_void_p) == 4:
        STRUCT_NAMES['flock'] = ['l_type', 'l_whence', 'l_start', 'l_len', 'l_sysid', 'l_pid', 'l_pad']
    else:
        STRUCT_NAMES['flock'] = ['l_type', 'l_whence', 'l_start', 'l_len', 'l_pid']
elif _system == 'FreeBSD':
    STRUCT_NAMES['flock'] = ['l_start', 'l_len', 'l_pid', 'l_type', 'l_whence', 'l_sysid']
elif _system in ('NetBSD', 'OpenBSD', 'Darwin'):
    STRUCT_NAMES['flock'] = ['l_start', 'l_len', 'l_pid', 'l_type', 'l_whence']
elif _system == 'SunOS':
    STRUCT_NAMES['flock'] = ['l_type', 'l_whence', 'l_start', 'l_len', 'l_sysid', 'l_pid', 'l_pad']
else:
    # WinFsp exposes struct fuse_flock with the generic Linux field order, and Cygwin uses the Linux/BSD layout.
    STRUCT_NAMES['flock'] = ['l_type', 'l_whence', 'l_start', 'l_len', 'l_pid']

if platform.system() == 'SunOS':
    STRUCT_NAMES['statvfs'] += ['f_basetype', 'f_fstr']

# libfuse < 2.8 (e.g., the illumos libfuse 2.7 used on OmniOS) has neither fuse_context.umask nor
# the fuse_conn_info members capable, want, max_background, and congestion_threshold.
# libfuse 2.8 has capable and want but not max_background and congestion_threshold.
# OpenBSD announces 2.6, but still has these struct members.
if mfusepy.fuse_version_major == 2 and platform.system() != 'OpenBSD':
    if mfusepy.fuse_version_minor < 8:
        STRUCT_NAMES['fuse_context'].remove('umask')
        STRUCT_NAMES['fuse_conn_info'] = ['proto_major', 'proto_minor', 'max_write', 'max_readahead']
    elif mfusepy.fuse_version_minor == 8:
        STRUCT_NAMES['fuse_conn_info'].remove('max_background')
        STRUCT_NAMES['fuse_conn_info'].remove('congestion_threshold')

if mfusepy.fuse_version_major == 3:
    STRUCT_NAMES['fuse_config'] = [
        'set_gid',
        'gid',
        'set_uid',
        'uid',
        'set_mode',
        'umask',
        'entry_timeout',
        'negative_timeout',
        'attr_timeout',
        'intr',
        'intr_signal',
        'remember',
        'hard_remove',
        'use_ino',
        'readdir_ino',
        'direct_io',
        'kernel_cache',
        'auto_cache',
    ]


C_CHECKER = r'''
#include <stdio.h>
#include <stddef.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <fcntl.h>
#include <fuse.h>

#define PRINT_STAT_MEMBER_OFFSET(NAME) \
    printf("stat.%s offset:%zu\n", #NAME, offsetof(struct stat, NAME));

#define PRINT_STATVFS_MEMBER_OFFSET(NAME) \
    printf("statvfs.%s offset:%zu\n", #NAME, offsetof(struct statvfs, NAME));

#define PRINT_FUSE_FILE_INFO_MEMBER_OFFSET(NAME) \
    printf("fuse_file_info.%s offset:%zu\n", #NAME, offsetof(struct fuse_file_info, NAME));

int main()
{
'''

PY_INFOS = {}
for struct_name, member_names in STRUCT_NAMES.items():
    fusepy_struct = getattr(
        mfusepy,
        struct_name,
        getattr(mfusepy, 'c_' + struct_name, getattr(mfusepy, 'c_' + struct_name + '_t', None)),
    )
    assert fusepy_struct is not None

    PY_INFOS[struct_name + " size"] = ctypes.sizeof(fusepy_struct)
    C_CHECKER += f"""\n    printf("{struct_name} size:%zu\\n", sizeof(struct {struct_name}));\n"""

    for name in member_names:
        PY_INFOS[f'{struct_name}.{name} offset'] = getattr(fusepy_struct, name).offset
        # This naming discrepancy is not good but would be an API change, I think.
        c_name = name.replace('timespec', 'time') if name.endswith('timespec') else name
        C_CHECKER += f'    printf("{struct_name}.{name} offset:%zu\\n", offsetof(struct {struct_name}, {c_name}));\n'


def first_set_bit(struct_type, field_name):
    value = struct_type()
    setattr(value, field_name, 1)
    raw = ctypes.string_at(ctypes.byref(value), ctypes.sizeof(value))
    for byte_index, byte in enumerate(raw):
        if byte:
            return byte_index * 8 + (byte & -byte).bit_length() - 1
    raise AssertionError(f"{struct_type.__name__}.{field_name} did not set any bit")


BITFIELD_NAMES = [
    field[0]
    for field in mfusepy.fuse_file_info._fields_
    if len(field) == 3 and not field[0].startswith(('padding', '__padd'))
]
PY_BITFIELD_INFOS = {}
for field_name in BITFIELD_NAMES:
    PY_BITFIELD_INFOS[field_name] = first_set_bit(mfusepy.fuse_file_info, field_name)
    C_CHECKER += f'''
    {{
        struct fuse_file_info value = {{0}};
        value.{field_name} = 1;
        const unsigned char * bytes = (const unsigned char *) &value;
        size_t byte_index = 0;
        while (bytes[byte_index] == 0) ++byte_index;
        unsigned int bit_index = 0;
        while ((bytes[byte_index] & (1u << bit_index)) == 0) ++bit_index;
        printf("fuse_file_info.{field_name} bit:%zu\\n", byte_index * 8 + bit_index);
    }}
'''

C_CHECKER += """
    return 0;
}
"""

print(C_CHECKER)


def get_compiler():
    compiler = os.environ.get('CC')
    if not compiler:
        for cc in ['cc', 'gcc', 'clang']:
            if shutil.which(cc):
                compiler = cc
                break
        else:
            compiler = 'cc'
    return compiler


def c_run(name: str, source: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        c_file = os.path.join(tmpdir, name + '.c')
        exe_file = os.path.join(tmpdir, name)
        preprocessed_file = os.path.join(tmpdir, name + '.preprocessed.c')

        with open(c_file, 'w', encoding='utf-8') as f:
            f.write(source)

        print(f"FUSE version: {mfusepy.fuse_version_major}.{mfusepy.fuse_version_minor}")

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

        # Add possible pkg-config flags if available
        for fuse_lib in () if mfusepy._librefuse else ("fuse", "fuse3"):
            try:
                pkg_config_flags = subprocess.check_output(['pkg-config', '--cflags', fuse_lib], text=True).split()
                cflags.extend(pkg_config_flags)
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

        cmd = [get_compiler(), *cflags, c_file, '-o', exe_file]
        print(f"Compiling with: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Compiler return code: {e.returncode}")
            print(f"Compiler stdout:\n{e.stdout}")
            print(f"Compiler stderr:\n{e.stderr}")
            assert e.returncode == 0, "Could not compile C program to verify sizes."

        cmd = [get_compiler(), '-E', *cflags, c_file, '-o', preprocessed_file]
        print(f"Preprocessing with: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Compiler return code: {e.returncode}")
            print(f"Compiler stdout:\n{e.stdout}")
            print(f"Compiler stderr:\n{e.stderr}")
            assert e.returncode == 0, "Could not compile C program to verify sizes."

        for line in Path(preprocessed_file).read_text().split('\n'):
            if not line.startswith('#') and line:
                print(line)
        print(preprocessed_file)

        output = subprocess.check_output([exe_file], text=True)
        return output


@pytest.fixture(scope='module')
def c_output():
    if os.name == 'nt':
        pytest.skip("C compiler check not implemented for Windows")
    return c_run("verify_structs", C_CHECKER)


def test_struct_layout(c_output):
    c_infos = {line.split(':', 1)[0]: int(line.split(':', 1)[1]) for line in c_output.strip().split('\n')}
    pprint.pprint(c_infos)

    fail = False
    for struct_name, member_names in STRUCT_NAMES.items():
        key = f"{struct_name} size"
        if c_infos[key] == PY_INFOS[key]:
            print(f"OK: {key} = {c_infos[key]}")
        else:
            print(f"Mismatch for {key}: C={c_infos[key]}, Python={PY_INFOS[key]}")
            fail = True

        for name in member_names:
            key = f"{struct_name}.{name} offset"
            if c_infos[key] == PY_INFOS[key]:
                print(f"OK: {key} = {c_infos[key]}")
            else:
                print(f"Mismatch for {key}: C={c_infos[key]}, Python={PY_INFOS[key]}")
                fail = True

    assert not fail, "Struct layout mismatch, see stdout output for details!"


def test_flock_is_a_structure():
    assert issubclass(mfusepy.c_flock_t, ctypes.Structure)
    assert mfusepy.c_flock_t._fields_
    assert ctypes.sizeof(mfusepy.c_flock_t) > ctypes.sizeof(ctypes.c_void_p)


def test_lock_callback_uses_flock_pointer():
    lock_field = next(field for field in mfusepy.fuse_operations._fields_ if field[0] == 'lock')
    assert lock_field[1]._argtypes_[-1] == ctypes.POINTER(mfusepy.c_flock_t)


@pytest.mark.skipif(sys.byteorder != 'little', reason="Bit numbering in the C test assumes little endian.")
def test_file_info_bitfields(c_output):
    c_infos = {line.split(':', 1)[0]: int(line.split(':', 1)[1]) for line in c_output.strip().split('\n')}
    fail = False
    for field_name, python_bit in PY_BITFIELD_INFOS.items():
        key = f"fuse_file_info.{field_name} bit"
        if c_infos[key] == python_bit:
            print(f"OK: {key} = {c_infos[key]}")
        else:
            print(f"Mismatch for {key}: C={c_infos[key]}, Python={python_bit}")
            fail = True
    assert not fail, "Bitfield layout mismatch, see stdout output for details!"
