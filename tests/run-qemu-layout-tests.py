#!/usr/bin/env python3
"""Run the struct layout and callback prototype probes on local cross targets.

The CI uses containers under QEMU. This helper uses locally installed cross compilers and
qemu-user binaries instead. Missing tools are reported with install hints and skipped.
"""

import argparse
import ctypes
import dataclasses
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))

try:
    import mfusepy  # noqa: E402
except Exception as error:  # noqa: BLE001
    print(f'[skip] all targets: cannot import mfusepy: {error}')
    print('       install libfuse2 or libfuse3, or set FUSE_LIBRARY_PATH')
    sys.exit(0)

from struct_layout_utils import (  # noqa: E402
    KERNEL_MEMBER_SIZE_SKIPS,
    KERNEL_STRUCTS,
    SKIP_MEMBERS,
    StructSpec,
    build_checks,
    c_probe,
    format_layout_diff,
    function_prototype_checks,
    parse_c_output,
    python_layout,
)

INCLUDES = ('sys/stat.h', 'sys/statvfs.h', 'fcntl.h', 'time.h', 'utime.h', 'fuse.h')
TARGETS: dict[str, tuple[str, Optional[str], Optional[str], str]] = {
    'aarch64': ('aarch64-linux-gnu-gcc', 'qemu-aarch64', '/usr/aarch64-linux-gnu', 'aarch64'),
    'riscv64': ('riscv64-linux-gnu-gcc', 'qemu-riscv64', '/usr/riscv64-linux-gnu', 'riscv64'),
    'ppc64le': ('powerpc64le-linux-gnu-gcc', 'qemu-ppc64le', '/usr/powerpc64le-linux-gnu', 'ppc64le'),
    'i686': ('gcc', None, None, 'i686'),
}
INSTALL_HINTS = {
    'aarch64': 'sudo apt-get install gcc-aarch64-linux-gnu qemu-user',
    'riscv64': 'sudo apt-get install gcc-riscv64-linux-gnu qemu-user',
    'ppc64le': 'sudo apt-get install gcc-powerpc64le-linux-gnu qemu-user',
    'i686': 'sudo apt-get install gcc-multilib libc6-dev-i386 python3:i386',
}


def fuse_include_dir() -> Optional[Path]:
    directory_names = ('fuse3',) if mfusepy.fuse_version_major == 3 else ('fuse',)
    candidates = [Path('/usr/local/include') / name for name in directory_names]
    candidates += [Path('/usr/include') / name for name in directory_names]
    candidates += [Path('/usr/local/include/osxfuse/fuse'), Path('/usr/local/include/macfuse/fuse')]
    for candidate in candidates:
        if (candidate / 'fuse.h').exists():
            return candidate
    return None


def struct_specs(types) -> list[StructSpec]:
    specs = [
        StructSpec(
            python_name=python_name,
            c_name=c_name,
            key=c_name,
            skip_members=tuple(SKIP_MEMBERS.get(c_name, ())),
            skip_member_sizes=KERNEL_MEMBER_SIZE_SKIPS.get(c_name, ()),
            member_sizes=True,
            member_types=True,
        )
        for python_name, c_name in KERNEL_STRUCTS
    ]
    for name in dir(types):
        ctype = getattr(types, name)
        if not name.startswith('fuse_') or not isinstance(ctype, type) or not issubclass(ctype, ctypes.Structure):
            continue
        if mfusepy.fuse_version_major == 2:
            if name == 'fuse_config':
                continue
            if (mfusepy.fuse_version_minor < 9 or mfusepy._librefuse) and name in ('fuse_buf', 'fuse_bufvec'):
                continue
        specs.append(StructSpec(python_name=name, c_name=name, member_sizes=True, member_types=True))
    return specs


def run_cross_target(target: str, fuse_include: Path) -> Optional[bool]:
    compiler_name, qemu_name, sysroot, machine = TARGETS[target]
    compiler = shutil.which(compiler_name) if compiler_name else None
    qemu = shutil.which(qemu_name) if qemu_name else None
    missing = []
    if compiler is None:
        missing.append(compiler_name)
    if qemu is None:
        missing.append(qemu_name or 'qemu')
    if sysroot is None:
        missing.append('target sysroot')
    elif not Path(sysroot, 'include', 'sys', 'stat.h').exists():
        missing.append(f'{sysroot}/include/sys/stat.h')
    if missing:
        print(f"[skip] {target}: missing {', '.join(missing)}")
        print(f"       {INSTALL_HINTS[target]}")
        return None

    assert compiler is not None
    assert qemu is not None
    assert sysroot is not None

    context = dataclasses.replace(mfusepy._context, system='Linux', machine=machine)
    types = mfusepy._FuseTypes(context)
    checks = build_checks(types, struct_specs(types))
    prototypes = function_prototype_checks(types)
    source = c_probe(
        INCLUDES,
        checks,
        prototypes,
        ('    (void) check_fuse_operations;',) if prototypes else (),
    )

    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / 'probe.c'
        executable = Path(directory) / 'probe'
        source_path.write_text(source)
        compile_command = [
            compiler,
            f'-DFUSE_USE_VERSION={mfusepy.fuse_version_major}{mfusepy.fuse_version_minor}',
            '-D_FILE_OFFSET_BITS=64',
            '-Werror=incompatible-pointer-types',
            f'-I{sysroot}/include',
            f'-I{fuse_include}',
            str(source_path),
            '-o',
            str(executable),
        ]
        try:
            subprocess.run(compile_command, check=True, capture_output=True, text=True)
            output = subprocess.check_output([qemu, '-L', sysroot, str(executable)], text=True)
        except subprocess.CalledProcessError as error:
            print(f'[fail] {target}: probe failed')
            if error.stderr:
                print(error.stderr)
            return False

    c_layout = parse_c_output(output)
    py_layout = python_layout(checks)
    differences = {
        key: (py_layout.get(key), c_layout.get(key))
        for key in set(py_layout) | set(c_layout)
        if py_layout.get(key) != c_layout.get(key)
    }
    if differences:
        print(f'[fail] {target}: layout differences')
        print(format_layout_diff(py_layout, c_layout))
        return False
    print(f'[ok] {target}')
    return True


def run_i686() -> Optional[bool]:
    print('[skip] i686: local checks need a 32-bit Python, linux32, and gcc -m32')
    print('       Use the CI QEMU job for the authoritative i686 check.')
    print(f"       {INSTALL_HINTS['i686']}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'targets',
        nargs='*',
        choices=tuple(TARGETS),
        default=tuple(TARGETS),
        help='Targets to check. Defaults to all supported targets.',
    )
    arguments = parser.parse_args()

    fuse_include = fuse_include_dir()
    if fuse_include is None:
        print('[skip] all targets: no host FUSE headers found')
        print('       sudo apt-get install libfuse-dev   # or libfuse3-dev')
        return 0

    results = {}
    for target in arguments.targets:
        results[target] = run_i686() if target == 'i686' else run_cross_target(target, fuse_include)

    passed = sum(result is True for result in results.values())
    skipped = sum(result is None for result in results.values())
    failed = sum(result is False for result in results.values())
    print(f'Local cross-target layout checks: {passed} passed, {skipped} skipped, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
