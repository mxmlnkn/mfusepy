"""
Verify that the Python and C offsets and struct sizes match.

Originally made for NetBSD, but should also work on other OSes.
"""
import ctypes
import os
import sys

# 1. Compile a tiny C program to get the REAL OS offsets
c_source = """
#include <sys/types.h>
#include <sys/stat.h>
#include <stddef.h>
#include <stdio.h>

int main() {
    struct stat st;
    printf("C_MODE=%lu\\n", offsetof(struct stat, st_mode));
    printf("C_UID=%lu\\n", offsetof(struct stat, st_uid));
    printf("C_GID=%lu\\n", offsetof(struct stat, st_gid));
    printf("C_RDEV=%lu\\n", offsetof(struct stat, st_rdev));
    printf("C_SIZE=%lu\\n", offsetof(struct stat, st_size));
    printf("C_FLAGS=%lu\\n", offsetof(struct stat, st_flags));
    printf("C_TOTAL=%lu\\n", sizeof(struct stat));
    return 0;
}
"""
with open("check_st.c", "w") as f:
    f.write(c_source)

os.system("cc check_st.c -o check_st")

print("--- OS C OFFSETS ---")
sys.stdout.flush()
os.system("./check_st")

# 2. Check mfusepy's Python offsets
import mfusepy

print("\n--- PYTHON CTYPES OFFSETS ---")
st = mfusepy.c_stat
print(f"PY_MODE={getattr(st.st_mode, 'offset', 'N/A')}")
print(f"PY_UID={getattr(st.st_uid, 'offset', 'N/A')}")
print(f"PY_GID={getattr(st.st_gid, 'offset', 'N/A')}")
print(f"PY_RDEV={getattr(st.st_rdev, 'offset', 'N/A')}")
print(f"PY_SIZE={getattr(st.st_size, 'offset', 'N/A')}")
print(f"PY_FLAGS={getattr(st.st_flags, 'offset', 'N/A')}")
print(f"PY_TOTAL={ctypes.sizeof(st)}")

