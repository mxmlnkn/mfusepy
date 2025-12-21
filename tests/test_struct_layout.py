import ctypes
import os
import shutil
import subprocess
import tempfile

import pytest

import mfusepy

STRUCT_NAMES = ["stat", "statvfs", "fuse_file_info"]

# we only check the struct members that are present on all supported platforms.

C_CHECKER = '''
#include <stdio.h>
#include <stddef.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <fuse.h>

int main() {
    // stat
    printf("stat_size:%zu\\n", sizeof(struct stat));
    printf("stat_st_atimespec_offset:%zu\\n", offsetof(struct stat, st_atime));
    printf("stat_st_blksize_offset:%zu\\n", offsetof(struct stat, st_blksize));
    printf("stat_st_blocks_offset:%zu\\n", offsetof(struct stat, st_blocks));
    printf("stat_st_ctimespec_offset:%zu\\n", offsetof(struct stat, st_ctime));
    printf("stat_st_dev_offset:%zu\\n", offsetof(struct stat, st_dev));
    printf("stat_st_gid_offset:%zu\\n", offsetof(struct stat, st_gid));
    printf("stat_st_ino_offset:%zu\\n", offsetof(struct stat, st_ino));
    printf("stat_st_mode_offset:%zu\\n", offsetof(struct stat, st_mode));
    printf("stat_st_mtimespec_offset:%zu\\n", offsetof(struct stat, st_mtime));
    printf("stat_st_nlink_offset:%zu\\n", offsetof(struct stat, st_nlink));
    printf("stat_st_rdev_offset:%zu\\n", offsetof(struct stat, st_rdev));
    printf("stat_st_size_offset:%zu\\n", offsetof(struct stat, st_size));
    printf("stat_st_uid_offset:%zu\\n", offsetof(struct stat, st_uid));
    // statvfs
    printf("statvfs_size:%zu\\n", sizeof(struct statvfs));
    printf("statvfs_f_bavail_offset:%zu\\n", offsetof(struct statvfs, f_bavail));
    printf("statvfs_f_bfree_offset:%zu\\n", offsetof(struct statvfs, f_bfree));
    printf("statvfs_f_blocks_offset:%zu\\n", offsetof(struct statvfs, f_blocks));
    printf("statvfs_f_bsize_offset:%zu\\n", offsetof(struct statvfs, f_bsize));
    printf("statvfs_f_favail_offset:%zu\\n", offsetof(struct statvfs, f_favail));
    printf("statvfs_f_ffree_offset:%zu\\n", offsetof(struct statvfs, f_ffree));
    printf("statvfs_f_files_offset:%zu\\n", offsetof(struct statvfs, f_files));
    printf("statvfs_f_flag_offset:%zu\\n", offsetof(struct statvfs, f_flag));
    printf("statvfs_f_frsize_offset:%zu\\n", offsetof(struct statvfs, f_frsize));
    printf("statvfs_f_fsid_offset:%zu\\n", offsetof(struct statvfs, f_fsid));
    printf("statvfs_f_namemax_offset:%zu\\n", offsetof(struct statvfs, f_namemax));
    // fuse_file_info - TODO: fix this later!
    printf("fuse_file_info_size:%zu\\n", sizeof(struct fuse_file_info));
    // printf("fuse_file_info_flags_offset:%zu\\n", offsetof(struct fuse_file_info, flags));
    // printf("fuse_file_info_fh_offset:%zu\\n", offsetof(struct fuse_file_info, fh));
    // printf("fuse_file_info_lock_owner_offset:%zu\\n", offsetof(struct fuse_file_info, lock_owner));
    return 0;
}
'''

py_infos = {
    # stat
    'stat_size': ctypes.sizeof(mfusepy.c_stat),
    'stat_st_atimespec_offset': mfusepy.c_stat.st_atimespec.offset,
    'stat_st_blksize_offset': mfusepy.c_stat.st_blksize.offset,
    'stat_st_blocks_offset': mfusepy.c_stat.st_blocks.offset,
    'stat_st_ctimespec_offset': mfusepy.c_stat.st_ctimespec.offset,
    'stat_st_dev_offset': mfusepy.c_stat.st_dev.offset,
    'stat_st_gid_offset': mfusepy.c_stat.st_gid.offset,
    'stat_st_ino_offset': mfusepy.c_stat.st_ino.offset,
    'stat_st_mode_offset': mfusepy.c_stat.st_mode.offset,
    'stat_st_mtimespec_offset': mfusepy.c_stat.st_mtimespec.offset,
    'stat_st_nlink_offset': mfusepy.c_stat.st_nlink.offset,
    'stat_st_rdev_offset': mfusepy.c_stat.st_rdev.offset,
    'stat_st_size_offset': mfusepy.c_stat.st_size.offset,
    'stat_st_uid_offset': mfusepy.c_stat.st_uid.offset,
    # statvfs
    'statvfs_size': ctypes.sizeof(mfusepy.c_statvfs),
    'statvfs_f_bavail_offset': mfusepy.c_statvfs.f_bavail.offset,
    'statvfs_f_bfree_offset': mfusepy.c_statvfs.f_bfree.offset,
    'statvfs_f_blocks_offset': mfusepy.c_statvfs.f_blocks.offset,
    'statvfs_f_bsize_offset': mfusepy.c_statvfs.f_bsize.offset,
    'statvfs_f_favail_offset': mfusepy.c_statvfs.f_favail.offset,
    'statvfs_f_ffree_offset': mfusepy.c_statvfs.f_ffree.offset,
    'statvfs_f_files_offset': mfusepy.c_statvfs.f_files.offset,
    'statvfs_f_flag_offset': mfusepy.c_statvfs.f_flag.offset,
    'statvfs_f_frsize_offset': mfusepy.c_statvfs.f_frsize.offset,
    'statvfs_f_fsid_offset': mfusepy.c_statvfs.f_fsid.offset,
    'statvfs_f_namemax_offset': mfusepy.c_statvfs.f_namemax.offset,
    # fuse_file_info - TODO: fix this later!
    'fuse_file_info_size': ctypes.sizeof(mfusepy.fuse_file_info),
    # 'fuse_file_info_flags_offset': mfusepy.fuse_file_info.flags.offset,
    # 'fuse_file_info_fh_offset': mfusepy.fuse_file_info.fh.offset,
    # 'fuse_file_info_lock_owner_offset': mfusepy.fuse_file_info.lock_owner.offset,
}

# Common locations for different OSes
INCLUDE_PATHS = [
    '/usr/local/include/fuse',
    '/usr/include/fuse',
    '/usr/local/include/fuse3',
    '/usr/include/fuse3',
    '/usr/local/include/osxfuse/fuse',
    '/usr/local/include/macfuse/fuse',
    '/usr/include/libfuse',
]


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

        with open(c_file, 'w', encoding='utf-8') as f:
            f.write(source)

        # Determine FUSE version and compile flags
        fuse_major = mfusepy.fuse_version_major
        fuse_minor = mfusepy.fuse_version_minor
        print(f"FUSE version: {fuse_major}.{fuse_minor}")

        cflags = [f'-DFUSE_USE_VERSION={fuse_major}{fuse_minor}', '-D_FILE_OFFSET_BITS=64']

        # Try to find fuse headers
        cflags += [f'-I{path}' for path in INCLUDE_PATHS if os.path.exists(path)]

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

        output = subprocess.check_output([exe_file], text=True)
        return output


@pytest.mark.skipif(os.name == 'nt', reason="C compiler check not implemented for Windows")
def test_struct_layout():
    output = c_run("verify_structs", C_CHECKER)
    c_infos = {}
    for line in output.strip().split('\n'):
        name, value = line.split(':')
        c_infos[name] = int(value)

    fail = False
    for struct_name in STRUCT_NAMES:
        key = f"{struct_name}_size"
        if c_infos[key] == py_infos[key]:
            print(f"OK: {key} = {c_infos[key]}")
        else:
            print(f"Mismatch for {key}: C={c_infos[key]}, Python={py_infos[key]}")
            fail = True
        struct_members = [
            (key, value)
            for key, value in c_infos.items()
            if key.startswith(struct_name + '_') and key.endswith("_offset")
        ]
        for key, _ in sorted(struct_members, key=lambda x: x[1]):  # sort by offset
            if c_infos[key] == py_infos[key]:
                print(f"OK: {key} = {c_infos[key]}")
            else:
                print(f"Mismatch for {key}: C={c_infos[key]}, Python={py_infos[key]}")
                fail = True
    assert not fail, "Struct layout mismatch, see stdout output for details!"
