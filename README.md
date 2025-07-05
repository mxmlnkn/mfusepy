# mfusepy

[![Python Version](https://img.shields.io/pypi/pyversions/mfusepy)](https://pypi.org/project/mfusepy/)
[![PyPI version](https://badge.fury.io/py/mfusepy.svg)](https://badge.fury.io/py/mfusepy)
[![Downloads](https://static.pepy.tech/badge/mfusepy/month)](https://pepy.tech/project/mfusepy)
[![Changelog](https://img.shields.io/badge/Changelog-Markdown-blue)](https://github.com/mxmlnkn/mfusepy/blob/master/CHANGELOG.md)
[![License](https://img.shields.io/badge/license-ISC-blue.svg)](http://opensource.org/licenses/ISC)
[![Build Status](https://github.com/mxmlnkn/mfusepy/actions/workflows/tests.yml/badge.svg)](https://github.com/mxmlnkn/mfusepy/actions)
[![Discord](https://img.shields.io/discord/783411320354766878?label=discord)](https://discord.gg/Wra6t6akh2)
[![Telegram](https://img.shields.io/badge/Chat-Telegram-%2330A3E6)](https://t.me/joinchat/FUdXxkXIv6c4Ib8bgaSxNg)

`mfusepy` is a Python module that provides a simple interface to [FUSE](https://docs.kernel.org/filesystems/fuse.html) and [macFUSE](https://osxfuse.github.io/).
It's just one file and is implemented using ctypes to use [libfuse](https://github.com/libfuse/libfuse).


# Installation

Via [PyPI](https://pypi.org/project/mfusepy/):

```bash
pip install mfusepy
```

You also need to install the `fuse` (2) or [`fuse3`](https://pkgs.org/search/?q=fuse3) package on your system.


# Versioning

This version tries to follow [semantic versioning](https://semver.org/).
If you depend on this project, you should fix the major version, or else you risk your project breaking on a newer version release!
E.g., in your pyproject.toml:

```toml
dependencies = ["mfusepy ~= 1.1",]
```

If you have tested with multiple major versions and they are known to work, you can also relax the check for maximum compatibility:

```toml
dependencies = ["mfusepy >= 1.1, < 3.0",]
```


# About this fork

This is a fork of [fusepy](https://github.com/fusepy/fusepy) because it did not see any development for over 6 years.
[Refuse](https://github.com/pleiszenburg/refuse/) was an attempt to fork fusepy, but it has not seen any development for over 4 years. Among lots of metadata changes, it contains two bugfixes to the high-level API, which I have redone in this fork.
See also the discussion in [this issue](https://github.com/mxmlnkn/ratarmount/issues/101).
I intend to maintain this fork as long as I maintain [ratarmount](https://github.com/mxmlnkn/ratarmount), which is now over 5 years old.

The main motivations for forking are:

 - [x] FUSE 3 support. Based on the [libfuse changelog](https://github.com/libfuse/libfuse/blob/master/ChangeLog.rst#libfuse-300-2016-12-08), the amount of breaking changes should be fairly small. It should be possible to simply update these ten or so changed structs and functions in the existing fusepy.
 - [x] Translation layer performance. In benchmarks for a simple `find` call for listing all files, some callbacks such as `readdir` turned out to be significantly limited by converting Python dictionaries to ctype structs. The idea would be to expose the ctype structs to the fusepy caller.
   - Much of the performance was lost trying to populate the stat struct even though only the mode member is used by the kernel FUSE API.

The prefix `m` in the name stands for anything you want it to: "multi" because multiple libfuse versions are supported, "modded", "modern", or "Maximilian".


# Comparison to other libraries

## High-level interface support (path-based)

| Project | License | Dependants | Notes
|-------------------------------------------------------|------|-----|------------------------|
| [fusepy](https://github.com/fusepy/fusepy)            | ISC  | [63](https://www.wheelodex.org/projects/fusepy/rdepends/) | The most popular Python-bindings, but unfortunately unmaintained for 6+ years. |
| [python-fuse](https://github.com/libfuse/python-fuse) | LGPL | [12](https://www.wheelodex.org/projects/fuse-python/rdepends/) | Written directly in C interfacing with `fuse.h` and exposing it via `Python.h`. Only supports libfuse2, not libfuse3. |
| [refuse](https://github.com/pleiszenburg/refuse)      | ISC  | [3](https://www.wheelodex.org/projects/refuse/rdepends/) | Dead fork of fusepy with many other dead forks: [[1]](https://github.com/yarikoptic/refuse) [[2]](https://github.com/YoilyL/refuse) |
| [fusepyng](https://pypi.org/project/fusepyng/)       | ISC  | [0](https://www.wheelodex.org/projects/fusepyng/rdepends/) | Dead fork of fusepy. Github repo has been force-pushed as a statement. Fork [here](https://github.com/djsutherland/fusepyng). |
| [userspacefs](https://pypi.org/project/userspacefs/)  | GPL3 (why not ISC?) | [1](https://www.wheelodex.org/projects/userspacefs/rdepends/) | Fork of fusepyng/fusepy. Gated behind self-hosting solution with no possibility to open issues or pull requests. |
| [fusepy3](https://github.com/fox-it/fusepy3)          | ISC  | Not on PyPI | Fork of fusepy for [fox-it/dissect](https://github.com/fox-it/dissect) ecosystem to add libfuse3 support. Seems to drop libfuse2 support though and it does not seem to work around the ABI [incompatibilities](https://github.com/libfuse/libfuse/issues/1029) between libfuse3 minor versions. Last update 1.5 years ago. Looks like publish and forget, or it may simply have no bugs. |


## Low-level interface support (inode/int-based)

All these libraries only wrap the low-level libfuse interface, which works with inodes instead of paths, and therefore are not (easily) usable for my use case.
In the end, there is mostly only some path-to-hash table in the high-level libfuse API, but it is cumbersome to implement and performance-critical.

| Project | License | Dependants | Notes
|------------------------------------------------------------------|------|-----|------------------------|
| [pyfuse3](https://github.com/libfuse/pyfuse3)                    | LGPL | [9](https://www.wheelodex.org/projects/pyfuse3/rdepends/) | ReadMe contains: "Warning - no longer developed!", and last release was 11 months ago. |
| [llfuse](https://github.com/python-llfuse/python-llfuse/)        | LGPL | [2](https://www.wheelodex.org/projects/llfuse/rdepends/) | ReadMe contains: ["Warning - no longer developed!"](https://github.com/python-llfuse/python-llfuse/issues/67), and last release was 11 months ago. |
| [arvados-llfuse](https://github.com/arvados/python-llfuse/)      | LGPL | [1](https://www.wheelodex.org/projects/arvados-llfuse/rdepends/) | Fork of llfuse, but less up to date? |
| [aliyundrive-fuse](https://github.com/messense/aliyundrive-fuse) | MIT  | [0](https://www.wheelodex.org/projects/aliyundrive-fuse/rdepends/) | Alibaba Cloud Disk FUSE disk mount "This repository has been archived by the owner on Mar 28, 2023". Only Chinese documentation. Only read support. Multiple fizzled out forks: [pikpak-fuse](https://github.com/ykxVK8yL5L/pikpak-fuse/), [alist-fuse](https://github.com/ykxVK8yL5L/alist-fuse) |


# Examples

See some examples of how you can use fusepy:

| Example                          | Description                                    |
|----------------------------------|------------------------------------------------|
| [memory](examples/memory.py)     | A simple memory filesystem                     |
| [loopback](examples/loopback.py) | A loopback filesystem                          |
| [context](examples/context.py)   | Sample usage of fuse_get_context()             |
| [sftp](examples/sftp.py)         | A simple SFTP filesystem (requires paramiko)   |


# Platforms

mfusepy requires FUSE 2.6 (or later) and runs on:

- Linux (i386, x86_64, PPC, arm64, MIPS)
- Mac OS X (Intel, PowerPC)
- FreeBSD (i386, amd64)

While FUSE is (at least in the Unix world) a [Kernel feature](https://man7.org/linux/man-pages/man4/fuse.4.html), several user space libraries exist for easy access.
`libfuse` acts as the reference implementation.

 - [libfuse](https://github.com/libfuse/libfuse) (Linux, FreeBSD) (fuse.h [2](https://github.com/libfuse/libfuse/blob/fuse-2_9_bugfix/include/fuse.h) [3](https://github.com/libfuse/libfuse/blob/master/include/fuse.h))
 - [libfuse](https://github.com/openbsd/src/tree/master/lib/libfuse) (OpenBSD) (fuse.h [2](https://github.com/openbsd/src/blob/master/lib/libfuse/fuse.h))
 - [librefuse](https://github.com/NetBSD/src/tree/netbsd-8/lib/librefuse) (NetBSD) through [PUFFS](https://en.wikipedia.org/wiki/PUFFS_(NetBSD)) (fuse.h [2](https://github.com/NetBSD/src/blob/netbsd-8/lib/librefuse/fuse.h))
 - [FUSE for macOS](https://github.com/osxfuse/osxfuse) (OSX) (fuse.h [2](https://github.com/osxfuse/fuse/blob/master/include/fuse.h))
 - [MacFUSE](https://code.google.com/archive/p/macfuse/) (OSX), no longer maintained
 - [MacFUSE](https://macfuse.github.io/) (OSX), [Github](https://github.com/macfuse/library)
 - [FUSE-T](https://www.fuse-t.org/) (OSX), [Github](https://github.com/macos-fuse-t/fuse-t)
 - [WinFsp](https://github.com/billziss-gh/winfsp) (Windows) (fuse.h [2](https://github.com/winfsp/winfsp/blob/master/inc/fuse/fuse.h) [3](https://github.com/winfsp/winfsp/blob/master/inc/fuse3/fuse.h))
 - [Dokany](https://github.com/dokan-dev/dokany) (Windows) (fuse.h [2](https://github.com/dokan-dev/dokany/blob/master/dokan_fuse/include/fuse.h))
 - [Dokan](https://code.google.com/archive/p/dokan/) (Windows), no longer maintained


# Known Dependants

 - [Megatron-Energon](https://github.com/NVIDIA/Megatron-Energon)
 - [ninfs](https://github.com/ihaveamac/ninfs)
 - [ratarmount](https://github.com/mxmlnkn/ratarmount)
