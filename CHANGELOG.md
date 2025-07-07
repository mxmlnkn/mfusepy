
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
