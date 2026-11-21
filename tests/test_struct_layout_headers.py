#!/usr/bin/env python3
"""
Compile the downloaded public headers and compare them with FuseTypes. E.g. run with:

    tests/headers/download.sh libfuse 3.18.3
    FUSE_LIBRARY_PATH=/path/to/libfuse3.so.3.18.3 \
    FUSE_INCLUDE_DIR="$PWD/tests/headers/libfuse/3.18.3/include/fuse3" \
    python3 -m pytest -q tests/test_struct_layout.py
"""

import ctypes
import dataclasses
import platform
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import mfusepy  # noqa: E402
except OSError:
    pytest.skip("No libfuse runtime library available for the module import.", allow_module_level=True)

from struct_layout_utils import (  # noqa: E402
    KERNEL_MEMBER_SIZE_SKIPS,
    KERNEL_STRUCTS,
    SKIP_MEMBERS,
    StructSpec,
    build_checks,
    c_probe,
    c_type_name,
    compile_and_run,
    find_compiler,
    format_layout_diff,
    function_prototype_checks,
    parse_c_output,
    python_layout,
)

HEADER_ROOT = ROOT / 'tests' / 'headers'
STRUCTS = tuple(
    name
    for name in dir(mfusepy)
    if name.startswith('fuse_')
    and isinstance(getattr(mfusepy, name), type)
    and issubclass(getattr(mfusepy, name), ctypes.Structure)
)

FuseContext = mfusepy._FuseContext


@dataclasses.dataclass(frozen=True)
class HeaderCase:
    name: str
    context: 'FuseContext'
    include_dir: Path
    header: str = ''
    includes: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    cflags: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    structs: tuple[str, ...] = dataclasses.field(default_factory=lambda: tuple(STRUCTS))
    kernel_structs: bool = False
    member_sizes: bool = True
    prototypes: bool = True
    skip_reason: str = ''


def compiled_layout(case: HeaderCase, types) -> tuple[dict[str, int], dict[str, int]]:
    if not case.include_dir.exists():
        pytest.skip(f"Missing {case.include_dir}; run tests/headers/download.sh")

    compiler = find_compiler()
    if compiler is None:
        pytest.skip("No C compiler available for the header matrix.")

    # Darwin system typedefs cannot be reproduced with a Linux compiler. Check exact member types on macOS only.
    member_types = not (case.context.system == 'Darwin' and sys.platform != 'darwin')
    structs = [
        StructSpec(python_name=name, c_name=name, member_sizes=case.member_sizes, member_types=member_types)
        for name in case.structs
    ]
    if case.kernel_structs:
        structs += [
            StructSpec(
                python_name=python_name,
                c_name=c_name,
                key=c_name,
                skip_members=tuple(SKIP_MEMBERS.get(c_name, ())),
                skip_member_sizes=KERNEL_MEMBER_SIZE_SKIPS.get(c_name, ()),
                member_sizes=True,
                member_types=member_types,
            )
            for python_name, c_name in KERNEL_STRUCTS
        ]
    checks = build_checks(types, structs)
    includes = (*case.includes, case.header) if case.header else case.includes
    fuse_prefix = getattr(case.context, 'system', '') == 'Windows'
    prototype_checks = (
        function_prototype_checks(types, fuse_prefix=fuse_prefix) if case.header and case.prototypes else []
    )
    source = c_probe(
        includes,
        checks,
        prototype_checks,
        ('    (void) check_fuse_operations;',) if prototype_checks else (),
    )
    cflags = [
        '-D_FILE_OFFSET_BITS=64',
        '-Werror=incompatible-pointer-types',
        *case.cflags,
        f'-I{case.include_dir}',
    ]
    try:
        output = compile_and_run(source, compiler=compiler, cflags=cflags)
    except subprocess.CalledProcessError as error:
        raise AssertionError(f"{case.name}: C compilation failed:\n{error.stderr}") from error

    return parse_c_output(output), python_layout(checks)


def header_cases() -> list[HeaderCase]:
    cases = []
    for version in sorted((HEADER_ROOT / 'libfuse').glob('*')):
        for include_name in ('fuse3', 'fuse'):
            include_dir = version / 'include' / include_name
            if not (include_dir / 'fuse.h').exists():
                continue
            if version.name == 'master':
                major, minor, hotfix = 3, 19, 0
            else:
                parts = version.name.split('.')
                if len(parts) < 2:
                    continue
                major, minor = int(parts[0]), int(parts[1])
                hotfix = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            structs = tuple(STRUCTS)
            if major == 2:
                structs = tuple(s for s in STRUCTS if s != 'fuse_config')
                if minor < 9:
                    structs = tuple(s for s in structs if s not in ('fuse_buf', 'fuse_bufvec'))
            cases.append(
                HeaderCase(
                    name=f"libfuse-{version.name}",
                    context=FuseContext(
                        system='Linux',
                        machine='x86_64',
                        fuse_version=(major, minor, hotfix),
                    ),
                    include_dir=include_dir,
                    header='fuse.h',
                    includes=('sys/stat.h', 'sys/statvfs.h', 'fcntl.h', 'time.h', 'utime.h'),
                    cflags=(f'-DFUSE_USE_VERSION={major}{minor}',),
                    structs=structs,
                    kernel_structs=True,
                )
            )
            break

    for version in sorted((HEADER_ROOT / 'cygfuse').glob('*')):
        include_dir = version / 'include'
        if (include_dir / 'fuse' / 'fuse.h').exists():
            cases.append(
                HeaderCase(
                    name=f"cygfuse-{version.name}",
                    context=FuseContext(
                        system='CYGWIN_NT-10.0',
                        machine='x86_64',
                        fuse_version=(2, 8, 0),
                    ),
                    include_dir=include_dir,
                    header='fuse/fuse.h',
                    cflags=('-D__CYGWIN__', '-DFSP_FUSE_API='),
                    structs=tuple(s for s in STRUCTS if s not in ('fuse_config', 'fuse_buf', 'fuse_bufvec')),
                )
            )

    for version in sorted((HEADER_ROOT / 'winfsp').glob('*')):
        include_dir = version / 'include'
        if (include_dir / 'fuse' / 'fuse.h').exists():
            try:
                winfsp_version = tuple(int(part) for part in version.name.split('.')[:2])
            except ValueError:
                winfsp_version = (0, 0)
            cases.append(
                HeaderCase(
                    name=f"winfsp-{version.name}",
                    context=FuseContext(
                        system='Windows',
                        machine='x86_64',
                        fuse_version=(2, 8, 0),
                    ),
                    include_dir=include_dir,
                    header='fuse/fuse.h',
                    cflags=('-D_WIN64', '-DFSP_FUSE_API=', '-D__declspec(x)='),
                    structs=tuple(s for s in STRUCTS if s not in ('fuse_config', 'fuse_buf', 'fuse_bufvec')),
                    skip_reason=(
                        "WinFsp before 1.11 lacks the getpath extension; the model targets 1.11+."
                        if winfsp_version < (1, 11)
                        else ''
                    ),
                )
            )

    macfuse_versions = {
        'support-libfuse-2.9': (2, 9, 0, '29', ''),
        'support-libfuse-3.17': (3, 17, 4, '317', ''),
        'support-libfuse-3.18': (3, 18, 3, '318', ''),
    }
    for version in sorted((HEADER_ROOT / 'macfuse').glob('*')):
        include_dir = version / 'include'
        if not (include_dir / 'fuse' / 'fuse.h').exists():
            continue
        if version.name in macfuse_versions:
            major, minor, hotfix, use_version, skip_reason = macfuse_versions[version.name]
            if major == 3:
                # macFUSE 3 enables Darwin-specific operations and argument types by default. Modeling that
                # operation ABI is future work, but the shared structs and the extended fuse_conn_info can
                # still be checked here.
                structs = tuple(s for s in STRUCTS if s != 'fuse_operations')
                prototypes = False
            else:
                structs = tuple(s for s in STRUCTS if s != 'fuse_config')
                prototypes = True
        else:
            major, minor, hotfix, use_version = (2, 9, 0, '29')
            structs = tuple(s for s in STRUCTS if s != 'fuse_config')
            prototypes = True
            skip_reason = (
                f"macFUSE branch {version.name!r} is not part of the checked release set. "
                "The matrix checks support/libfuse-2.9, 3.17, and 3.18."
            )
        cases.append(
            HeaderCase(
                name=f"macfuse-{version.name}",
                context=FuseContext(
                    system='Darwin',
                    machine='x86_64',
                    fuse_version=(major, minor, hotfix),
                ),
                include_dir=include_dir,
                header='fuse/fuse.h',
                cflags=('-D__APPLE__', f'-DFUSE_USE_VERSION={use_version}'),
                structs=structs,
                # The probe is compiled with the host's mode_t, so member sizes are not comparable.
                member_sizes=False,
                prototypes=prototypes,
                skip_reason=skip_reason,
            )
        )

    for project, system, fuse_version in (
        ('netbsd', 'NetBSD', (3, 10, 0)),
        ('openbsd', 'OpenBSD', (2, 6, 0)),
    ):
        for directory in sorted((HEADER_ROOT / project).glob('*')):
            include_dir = directory / 'include' / 'fuse'
            if (include_dir / 'fuse.h').exists():
                cases.append(
                    HeaderCase(
                        name=f"{project}-{directory.name}",
                        context=FuseContext(
                            system=system,
                            machine='x86_64',
                            fuse_version=fuse_version,
                            librefuse=system == 'NetBSD',
                        ),
                        include_dir=include_dir,
                        header='fuse.h',
                        structs=tuple(s for s in STRUCTS if s not in ('fuse_config', 'fuse_buf', 'fuse_bufvec')),
                        skip_reason=(
                            "NetBSD librefuse headers need a target sysroot."
                            if system == 'NetBSD' and platform.system() != 'NetBSD'
                            else ''
                        ),
                    )
                )

    if platform.system() == 'FreeBSD':
        for directory in sorted((HEADER_ROOT / 'freebsd').glob('*')):
            include_dir = directory / 'include'
            if (include_dir / 'sys' / 'stat.h').exists():
                cases.append(
                    HeaderCase(
                        name=f"freebsd-{directory.name}",
                        context=FuseContext(
                            system='FreeBSD',
                            machine='amd64',
                            fuse_version=(2, 9, 0),
                        ),
                        include_dir=include_dir,
                        includes=('sys/stat.h', 'sys/statvfs.h', 'fcntl.h', 'time.h', 'utime.h'),
                        structs=(),
                        kernel_structs=True,
                        member_sizes=True,
                    )
                )
    return cases


@pytest.mark.parametrize('case', header_cases(), ids=lambda case: case.name)
def test_downloaded_header_layout(case):
    if case.skip_reason:
        pytest.skip(case.skip_reason)
    types = mfusepy._FuseTypes(case.context)
    c_layout, py_layout = compiled_layout(case, types)
    assert py_layout == c_layout, f"{case.name}: layout mismatch\n{format_layout_diff(py_layout, c_layout)}"


def test_layout_diff_reports_size_hint():
    diff = format_layout_diff({'fuse_operations.size': 352}, {'fuse_operations.size': 360})
    assert 'C=360' in diff
    assert 'Python=352' in diff
    assert 'trailing field' in diff


def test_c_type_name_derives_struct_names():
    assert c_type_name(mfusepy.c_stat) == 'struct stat'
    assert c_type_name(mfusepy.c_flock_t) == 'struct flock'
    assert c_type_name(mfusepy.fuse_file_info) == 'struct fuse_file_info'
    assert c_type_name(mfusepy.c_stat, fuse_prefix=True) == 'struct fuse_stat'


def test_bmap_argument_uses_declared_uint64_type():
    types = mfusepy._FuseTypes(mfusepy._FuseContext(system='Linux', machine='x86_64', fuse_version=(2, 9, 9)))
    assert any('bmap((char *) 0, (size_t) 0, (uint64_t *) 0)' in line for line in function_prototype_checks(types))
