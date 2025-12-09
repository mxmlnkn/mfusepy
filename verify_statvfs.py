import ctypes
import os
import sys

import mfusepy

# 1. C Program to get authoritative statvfs offsets
c_source = """
#include <sys/types.h>
#include <sys/statvfs.h>
#include <stddef.h>
#include <stdio.h>

int main() {
    struct statvfs st;
    printf("C_FLAG=%lu\\n", offsetof(struct statvfs, f_flag));
    printf("C_BSIZE=%lu\\n", offsetof(struct statvfs, f_bsize));
    printf("C_FRSIZE=%lu\\n", offsetof(struct statvfs, f_frsize));
    printf("C_IOSIZE=%lu\\n", offsetof(struct statvfs, f_iosize));
    printf("C_BLOCKS=%lu\\n", offsetof(struct statvfs, f_blocks));
    printf("C_BFREE=%lu\\n", offsetof(struct statvfs, f_bfree));
    printf("C_BAVAIL=%lu\\n", offsetof(struct statvfs, f_bavail));
    printf("C_NAMEMAX=%lu\\n", offsetof(struct statvfs, f_namemax));
    printf("C_TOTAL=%lu\\n", sizeof(struct statvfs));
    return 0;
}
"""

with open("check_statvfs.c", "w") as f:
    f.write(c_source)

os.system("cc check_statvfs.c -o check_statvfs")

print("--- OS C OFFSETS ---")
sys.stdout.flush()
os.system("./check_statvfs")

# 2. Check mfusepy's Python offsets
print("\n--- PYTHON CTYPES OFFSETS ---")
st = mfusepy.c_statvfs


def get_off(name):
    if not hasattr(st, name):
        return "MISSING"
    return getattr(getattr(st, name), 'offset', 'N/A')


print(f"PY_FLAG={get_off('f_flag')}")
print(f"PY_BSIZE={get_off('f_bsize')}")
print(f"PY_FRSIZE={get_off('f_frsize')}")
print(f"PY_IOSIZE={get_off('f_iosize')}")
print(f"PY_BLOCKS={get_off('f_blocks')}")
print(f"PY_BFREE={get_off('f_bfree')}")
print(f"PY_BAVAIL={get_off('f_bavail')}")
print(f"PY_NAMEMAX={get_off('f_namemax')}")
print(f"PY_TOTAL={ctypes.sizeof(st)}")
