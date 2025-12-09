import ctypes
import os
import sys

import mfusepy

# 1. C Program to get authoritative OS offsets
c_source = """
#define _KERNTYPES
#include <sys/types.h>

#include <sys/cdefs.h>
#define FUSE_USE_VERSION FUSE_MAKE_VERSION(2, 6)

#include <fuse.h>
#include <stddef.h>
#include <stdio.h>

int main() {
    // FUSE_FILE_INFO
    printf("FI_FLAGS=%lu\\n", offsetof(struct fuse_file_info, flags));
    printf("FI_FH_OLD=%lu\\n", offsetof(struct fuse_file_info, fh_old));
    printf("FI_FH=%lu\\n", offsetof(struct fuse_file_info, fh));
    printf("FI_LOCK_OWNER=%lu\\n", offsetof(struct fuse_file_info, lock_owner));
    printf("FI_TOTAL=%lu\\n", sizeof(struct fuse_file_info));

    // FUSE_OPERATIONS (Function Pointers)
    printf("OP_GETATTR=%lu\\n", offsetof(struct fuse_operations, getattr));
    printf("OP_MKNOD=%lu\\n", offsetof(struct fuse_operations, mknod));
    printf("OP_MKDIR=%lu\\n", offsetof(struct fuse_operations, mkdir));
    printf("OP_OPEN=%lu\\n", offsetof(struct fuse_operations, open));
    printf("OP_READ=%lu\\n", offsetof(struct fuse_operations, read));
    printf("OP_WRITE=%lu\\n", offsetof(struct fuse_operations, write));
    printf("OP_ACCESS=%lu\\n", offsetof(struct fuse_operations, access));
    printf("OP_CREATE=%lu\\n", offsetof(struct fuse_operations, create));
    printf("OP_INIT=%lu\\n", offsetof(struct fuse_operations, init));
    printf("OP_TOTAL=%lu\\n", sizeof(struct fuse_operations));

    return 0;
}
"""

with open("check_structs.c", "w") as f:
    f.write(c_source)

print("Compiling C checker...")
# Added -Wl,-R/usr/pkg/lib so the binary finds the library at runtime
compile_cmd = "cc -D_FILE_OFFSET_BITS=64 -I/usr/pkg/include -L/usr/pkg/lib -Wl,-R/usr/pkg/lib -lfuse check_structs.c -o check_structs"

if os.system(compile_cmd) != 0:
    print("Compilation failed! Ensure fuse headers are installed (pkgin install fuse).")
    sys.exit(1)

print("--- OS C OFFSETS ---")
sys.stdout.flush()
os.system("./check_structs")

# 2. Check mfusepy's Python offsets
print("\n--- PYTHON CTYPES OFFSETS ---")

# Check fuse_file_info
fi = mfusepy.fuse_file_info
def get_off(cls, name):
    if not hasattr(cls, name): return "MISSING"
    return getattr(getattr(cls, name), 'offset', 'N/A')

print(f"FI_FLAGS={get_off(fi, 'flags')}")
print(f"FI_FH_OLD={get_off(fi, 'fh_old')}")
print(f"FI_FH={get_off(fi, 'fh')}")
print(f"FI_LOCK_OWNER={get_off(fi, 'lock_owner')}")
print(f"FI_TOTAL={ctypes.sizeof(fi)}")

# Check fuse_operations
op = mfusepy.fuse_operations
print(f"OP_GETATTR={get_off(op, 'getattr')}")
print(f"OP_MKNOD={get_off(op, 'mknod')}")
print(f"OP_MKDIR={get_off(op, 'mkdir')}")
print(f"OP_OPEN={get_off(op, 'open')}")
print(f"OP_READ={get_off(op, 'read')}")
print(f"OP_WRITE={get_off(op, 'write')}")
print(f"OP_ACCESS={get_off(op, 'access')}")
print(f"OP_CREATE={get_off(op, 'create')}")
print(f"OP_INIT={get_off(op, 'init')}")
print(f"OP_TOTAL={ctypes.sizeof(op)}")
