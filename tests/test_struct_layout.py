import ctypes
import os
import platform
import pprint
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import mfusepy

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

if platform.system() != 'NetBSD':
    STRUCT_NAMES['fuse_file_info'] = ['flags', 'fh', 'lock_owner']

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
    fusepy_struct = getattr(mfusepy, struct_name, getattr(mfusepy, 'c_' + struct_name, None))
    assert fusepy_struct is not None

    PY_INFOS[struct_name + " size"] = ctypes.sizeof(fusepy_struct)
    C_CHECKER += f"""\n    printf("{struct_name} size:%zu\\n", sizeof(struct {struct_name}));\n"""

    for name in member_names:
        PY_INFOS[f'{struct_name}.{name} offset'] = getattr(fusepy_struct, name).offset
        # This naming discrepancy is not good but would be an API change, I think.
        c_name = name.replace('timespec', 'time') if name.endswith('timespec') else name
        C_CHECKER += f'    printf("{struct_name}.{name} offset:%zu\\n", offsetof(struct {struct_name}, {c_name}));\n'

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
        ]
        if mfusepy.fuse_version_major == 3:
            include_paths += ['/usr/local/include/fuse3', '/usr/include/fuse3']
        else:
            include_paths += ['/usr/local/include/fuse', '/usr/include/fuse']

        cflags = [
            f'-DFUSE_USE_VERSION={mfusepy.fuse_version_major}{mfusepy.fuse_version_minor}',
            '-D_FILE_OFFSET_BITS=64',
        ]
        cflags += [f'-I{path}' for path in include_paths if os.path.exists(path)]

        # Add possible pkg-config flags if available
        for fuse_lib in ("fuse", "fuse3"):
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


@pytest.mark.skipif(os.name == 'nt', reason="C compiler check not implemented for Windows")
def test_struct_layout():
    output = c_run("verify_structs", C_CHECKER)
    c_infos = {line.split(':', 1)[0]: int(line.split(':', 1)[1]) for line in output.strip().split('\n')}
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
