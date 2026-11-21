
# Version 3.2.0 built on 2026-11-21

## Features

 - Add `posix_acl_to_xattr` and `posix_acl_from_xattr`, plus the `PosixACLEntry`, `ACLTag`, and
   `ACLPermission` helpers and `XATTR_NAME_POSIX_ACL_*` constants for the Linux `system.posix_acl_*`
   xattr format. Entries are validated and sorted into the canonical order required by the kernel. The
   helpers raise `NotImplementedError` outside Linux. See `examples/posix_acl.py`.
 - Add the cross-platform `FuseCapability` enum and `fuse_conn_info.is_capable`,
   `enable_capability`, and `disable_capability`, which map capabilities to the loaded implementation
   and support `fuse_set_feature_flag` from libfuse 3.17+.
 - Add the `syncfs` callback to `fuse_operations` for libfuse 3.19.
 - Support OmniOS, including the illumos libfuse 2.7 struct layout and 64-bit library lookup.
 - Add Python 3.15 to the supported versions.
 - Implement `flock` in `examples/loopback.py`, `examples/memory.py`, and `examples/memory_nullpath.py`
   and request `FLOCK_LOCKS`.
 - Document the macOS-only `position` argument of the `getxattr` and `setxattr` callbacks.

## Fixes

 - Keep the public ctypes structure classes picklable after their construction moved into the
   `_FuseTypes` factory.
 - Return `EIO` instead of relying on an assertion when a `read` callback returns more bytes than
   requested.
 - Model the `fuse_file_info` fields added in libfuse 3.17 and 3.18.3 (`backing_id`, `compat_flags`,
   and `kill_suidgid`).
 - Correct `fuse_file_info.poll_events` to 32-bit, `fuse_config.parallel_direct_writes` for 3.14.1,
   `fuse_conn_info.request_timeout` for 3.18, `fuse_buf.mem_size` and the `fuse_bufvec` layout, and
   the FUSE 2.8 `poll` operation. Use the patch-level version from `fuse_pkgversion()` so that
   releases such as 3.14.1 and 3.18.3 select the correct layout.
 - Define `struct flock` per platform and check the lock callback argument.
 - Use `struct timespec[2]` for the `utimens` callback and `time_t` for `c_utimbuf`.
 - Add `flag_nopath`/`flag_utime_omit_ok` only from libfuse 2.9 and `fallocate` only from 2.9.1.
   Use the 2.9.1+ layout for all 2.9 runtimes because the FUSE 2 runtime does not expose the hotfix.
 - Gate `copy_file_range` to libfuse 3.4+ and `lseek` to 3.8+.
 - Use 64-bit `dev_t` and `st_gen` on FreeBSD.
 - Apply the libfuse 2 `nopath` option as `fuse_config.nullpath_ok` instead of aborting the mount.
 - Accept a missing path in the `write_buf`, `read_buf`, and `flock` wrappers when
   `nopath`/`nullpath_ok` is set.
 - Reject unknown Linux architectures instead of silently using the i686 `struct stat` layout.
 - Correct the macFUSE 5.5.0 and WinFsp `fuse_operations` layouts, including the WinFsp
   `getdir`/`readlink` order that broke symlinks and the missing extension fields.
 - Correct the Cygwin `fuse_file_info` and `fuse_operations` layouts and do not use WinFsp-specific
   behavior there.
 - Do not advertise the WinFsp `STAT_EX` and `DELETE_ACCESS` capabilities until the extended stat
   layout and delete-access semantics are modeled.
 - Reset the reused `stat` buffer between `readdir` entries.
 - Fix the `struct stat` layout on Linux riscv64.
 - Fix the `struct stat` layout on Linux PPC by adding the trailing glibc reserved fields.
 - Correct the `destroy` callback prototype to return `void` instead of `void *`.
 - Remove the legacy MacFuse lookup, which could abort `import mfusepy` on macOS 14 with macFUSE 5.3.x.
 - Fix the `fuse_context` size for libfuse < 2.8.
 - NetBSD: use the base-system librefuse instead of libfuse and perfused, call `__fuse_main` with the
   FUSE 3 operations layout, detect librefuse via `fuse_pkgversion`, fail at import if `__fuse_main`
   is missing, and fall back to the soname when `find_library` fails.
 - Use the correct 32-bit return type for the NetBSD `getxattr` callback.
 - Add the glibc `__f_unused` pad to the 32-bit Linux `statvfs` layout.
 - Do not swallow exceptions raised by the `init` callback. They are now re-raised instead of being
   returned as a bogus `private_data` pointer.
 - `examples/loopback.py`: do not follow symlinks in `chmod` and `chown`, and report `st_ino` so hard
   links work.
 - `examples/context.py`: honor the requested read size and offset and implement `open` for OpenBSD.
 - `examples/memory.py`: keep asynchronous reads enabled.
 - `examples/memory_nullpath.py`: report `st_ino` for symlinks.

## Build

 - Allow setuptools < 85 instead of < 83.
 - Ship `tests/` and `examples/` in the source distribution so packagers can run the test suite.

## Limitations

 - The libfuse 3.18 `statx` callback is modeled as a placeholder in `fuse_operations` and is not
   implemented.


# Version 3.1.1 built on 2026-03-13

## Fixes

 - Pin to setuptools < 83 instead of <= 82 to allow matches against 82.0.1 and higher.
   It still is pinned to <83 because of the
   [license specifier API break disaster](https://github.com/pypa/setuptools/issues/4903).


# Version 3.1.0 built on 2025-12-23

Most of the fixes and test/CI improvements were contributed by Thomas Waldmann. Many thanks!
NetBSD is still work-in-progress.

## API

 - Add many more missing type hints.

## Features

 - Add `mfusepy.ENOATTR` to be used as the correct value for `getxattr` and `removexattr`.
 - Make path decode/encode error policy configurable and switch from `strict` to `surrogateescape`.
 - Add `readdir_with_offset` implementable interface method, which takes an additional `offset` argument.
   Does not work correctly on OpenBSD. Help would be welcome.
 - Translate some of the libfuse2-only options (`use_ino`, `direct_io`, `nopath`, ...) to the libfuse3 config struct.
 - Allow to set fuse library name via `FUSE_LIBRARY_NAME` environment variable.
 - Automatically test and therefore support Ubuntu 22.04/24.04 aarch64/x86_64, macOS 14/15 Intel/ARM,
   FreeBSD 14.3, OpenBSD 7.7, NetBSD 10.1.

## Fixes

 - Fix type definitions and examples on OpenBSD, FreeBSD, NetBSD, macOS, and others.
 - `readdir`: Also forward `st_ino` in case `use_ino` is set to True.
 - Avoid `readdir` infinite loop by ignoring the offset and returning offset 0, to trigger non-offset mode.
   Overwrite `readdir_with_offset` to actually make use of offsets.
 - `getattr_fuse_3`: pass argument `fip` to `fgetattr`.
 - Avoid null pointer dereferences for `fip` in `ftruncate`, `fgetattr`, and `lock`.


# Version 3.0.0 built on 2025-08-01

Version 2 was skipped because the git tags would have clashed with the original fusepy tags.

## API

 - `Operation.__call__` is not used anymore. Use decorators instead, or check `LoggingMixIn` as to how to overwrite
   `__getattribute__`. This is the biggest change requiring an API break and was motivated by the type support.
 - Add type-hints. Do not check types at runtime! They may change in a major version,
   .e.g., `List` -> `list` -> `Sequence` -> `Iterable`.
 - `readdir` may now also return only a triple of (name, mode, offset).
 - `init_with_config` arguments are now always structs. Prior, they were ctypes pointers to the struct.
 - As the old warning stated, `use_ns` will be removed in version 4 and all timestamps will use nanoseconds then.
   Set `FUSE.use_ns = True` and then return only times as integers representing nanoseconds and expect returned
   times as such.

## Features

 - Add `overrides` decorator.
 - Add `log_callback` decorator.


# Version 1.1.1 built on 2025-07-07

## Fixes

 - Forward return code for `utimens` and `rename`.
 - Restore compatibility with old fusepy implementations that implement `create` with only 2 arguments.
 - If FUSE 2 flag_nullpath_ok and flag_nopath members exist, then enable fuse_config.nullpath_ok in FUSE 3.
 - Handle possible null path in all methods mentioned in nullpath_ok documentation.


# Version 1.1.0 built on 2025-05-08

## Features

 - Support libfuse 3.17+.


# Version 1.0.0 built on 2024-10-27

 - First version with libfuse3 support.
