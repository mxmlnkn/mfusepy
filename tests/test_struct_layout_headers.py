#!/usr/bin/env python3
"""
Compile the downloaded public headers and compare them with FuseTypes. E.g. run with:

    tests/headers/download.sh libfuse 3.18.3
    FUSE_LIBRARY_PATH=/path/to/libfuse3.so.3.18.3 \
    FUSE_INCLUDE_DIR="$PWD/tests/headers/libfuse/3.18.3/include/fuse3" \
    python3 -m pytest -q tests/test_struct_layout.py
"""

import ctypes
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import mfusepy  # noqa: E402
except OSError:
    pytest.skip("No libfuse runtime library available for the module import.", allow_module_level=True)

from struct_layout_utils import (  # noqa: E402
    StructSpec,
    build_checks,
    c_probe,
    compile_and_run,
    find_compiler,
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


@dataclass(frozen=True)
class HeaderCase:
    name: str
    context: 'FuseContext'
    include_dir: Path
    header: str
    cflags: tuple[str, ...] = field(default_factory=tuple)
    structs: tuple[str, ...] = field(default_factory=lambda: tuple(STRUCTS))
    compile_skip: bool = False
    member_sizes: bool = True


def compiled_layout(case: HeaderCase, types) -> tuple[dict[str, int], dict[str, int]]:
    if not case.include_dir.exists():
        pytest.skip(f"Missing {case.include_dir}; run tests/headers/download.sh")

    compiler = find_compiler()
    if compiler is None:
        pytest.skip("No C compiler available for the header matrix.")

    structs = tuple(
        StructSpec(
            python_name=name,
            c_name=name,
            member_sizes=case.member_sizes,
            bitfields=name == 'fuse_file_info',
        )
        for name in case.structs
    )
    checks = build_checks(types, structs)
    source = c_probe((case.header,), checks)
    cflags = ['-D_FILE_OFFSET_BITS=64', *case.cflags, f'-I{case.include_dir}']
    try:
        output = compile_and_run(source, compiler=compiler, cflags=cflags)
    except subprocess.CalledProcessError as error:
        if case.compile_skip:
            pytest.skip(f"{case.name}: C compilation is not portable: {error.stderr.strip()}")
        raise AssertionError(f"{case.name}: C compilation failed:\n{error.stderr}") from error

    return parse_c_output(output), python_layout(checks)


def header_cases() -> list[HeaderCase]:
    cases = []
    for version in sorted((HEADER_ROOT / 'libfuse').glob('*')):
        for include_name in ('fuse3', 'fuse'):
            include_dir = version / 'include' / include_name
            if not (include_dir / 'fuse.h').exists():
                continue
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
                    cflags=(f'-DFUSE_USE_VERSION={major}{minor}',),
                    structs=structs,
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
                    compile_skip=True,
                )
            )

    for version in sorted((HEADER_ROOT / 'macfuse').glob('*')):
        include_dir = version / 'include'
        if (include_dir / 'fuse' / 'fuse.h').exists():
            cases.append(
                HeaderCase(
                    name=f"macfuse-{version.name}",
                    context=FuseContext(
                        system='Darwin',
                        machine='x86_64',
                        fuse_version=(2, 9, 0),
                    ),
                    include_dir=include_dir,
                    header='fuse/fuse.h',
                    cflags=('-D__APPLE__', '-DFUSE_USE_VERSION=29'),
                    structs=tuple(s for s in STRUCTS if s != 'fuse_config'),
                    compile_skip=True,
                    # The probe is compiled with the host's mode_t, so member sizes are not comparable.
                    member_sizes=False,
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
                        compile_skip=system == 'NetBSD',
                    )
                )
    return cases


@pytest.mark.parametrize('case', header_cases(), ids=lambda case: case.name)
def test_downloaded_header_layout(case):
    types = mfusepy._FuseTypes(case.context)
    c_layout, py_layout = compiled_layout(case, types)
    assert py_layout == c_layout
