
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
