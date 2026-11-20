"""Compile C probes and compare them with the ctypes structure layouts."""

import ctypes
import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

KERNEL_STRUCTS = [
    ('c_stat', 'stat'),
    ('c_statvfs', 'statvfs'),
    ('c_flock_t', 'flock'),
    ('c_timespec', 'timespec'),
    ('c_utimbuf', 'utimbuf'),
]
# Fields that are padding, have an unstable C name, or are optional libc extensions.
SKIP_MEMBERS = {
    'stat': {'reserved', 'st_birthtimespec'},
    # f_type is a glibc extension that Ubuntu 22.04 headers do not declare.
    'statvfs': {'f_type'},
}
# The Linux C member is st_atim, while the ctypes model uses the BSD st_atimespec name. The offset
# matches through the st_atime macro, but the size of the scalar macro is not the timespec size.
KERNEL_MEMBER_SIZE_SKIPS = {
    'stat': ('st_atimespec', 'st_mtimespec', 'st_ctimespec', 'st_birthtimespec'),
}


def find_compiler() -> Optional[str]:
    if compiler := os.environ.get('CC'):
        return compiler
    for name in ('cc', 'gcc', 'clang'):
        if compiler := shutil.which(name):
            return compiler
    return None


def first_set_bit(struct_type, field_name: str) -> int:
    value = struct_type()
    setattr(value, field_name, 1)
    raw = ctypes.string_at(ctypes.byref(value), ctypes.sizeof(value))
    for byte_index, byte in enumerate(raw):
        if byte:
            return byte_index * 8 + (byte & -byte).bit_length() - 1
    raise AssertionError(f"{struct_type.__name__}.{field_name} did not set any bit")


def is_padding(name: str) -> bool:
    return name.startswith(('_', 'padding'))


def c_member_name(member: str) -> str:
    # The ctypes definitions use the BSD name for all platforms because it is more explicit.
    return member.replace('timespec', 'time') if member.endswith('timespec') else member


@dataclass(frozen=True)
class StructSpec:
    """One ctypes structure and the C structure it should match."""

    python_name: str
    c_name: str
    key: Optional[str] = None
    members: Optional[tuple[str, ...]] = None
    skip_members: tuple[str, ...] = ()
    skip_member_sizes: tuple[str, ...] = ()
    member_sizes: bool = False

    @property
    def name(self) -> str:
        return self.key if self.key is not None else self.python_name


@dataclass(frozen=True)
class LayoutCheck:
    key: str
    value: int
    c_lines: tuple[str, ...]


def _bitfield_lines(key: str, c_name: str, member: str) -> tuple[str, ...]:
    return (
        '    {',
        f'        struct {c_name} value = {{0}};',
        f'        value.{member} = 1;',
        '        const unsigned char * bytes = (const unsigned char *) &value;',
        '        size_t byte_index = 0;',
        '        while (bytes[byte_index] == 0) ++byte_index;',
        '        unsigned int bit_index = 0;',
        '        while ((bytes[byte_index] & (1u << bit_index)) == 0) ++bit_index;',
        f'        printf("{key}:%zu\\n", byte_index * 8 + bit_index);',
        '    }',
    )


def build_checks(types, structs: Sequence[StructSpec]) -> list[LayoutCheck]:
    checks = []
    for spec in structs:
        struct_type = getattr(types, spec.python_name, None)
        if struct_type is None:
            continue

        name = spec.name
        checks.append(
            LayoutCheck(
                f'{name}.size',
                ctypes.sizeof(struct_type),
                (f'    printf("{name}.size:%zu\\n", sizeof(struct {spec.c_name}));',),
            )
        )

        fields = getattr(struct_type, '_fields_', ())
        bitfield_names = {field[0] for field in fields if len(field) == 3}
        member_names = spec.members
        if member_names is None:
            member_names = tuple(
                field[0] for field in fields if not is_padding(field[0]) and field[0] not in spec.skip_members
            )

        for member in member_names:
            if member in bitfield_names:
                key = f'{name}.{member} bit'
                checks.append(
                    LayoutCheck(
                        key,
                        first_set_bit(struct_type, member),
                        _bitfield_lines(key, spec.c_name, member),
                    )
                )
                continue

            c_member = c_member_name(member)
            checks.append(
                LayoutCheck(
                    f'{name}.{member} offset',
                    getattr(struct_type, member).offset,
                    (f'    printf("{name}.{member} offset:%zu\\n", offsetof(struct {spec.c_name}, {c_member}));',),
                )
            )
            if spec.member_sizes and member not in spec.skip_member_sizes:
                checks.append(
                    LayoutCheck(
                        f'{name}.{member} size',
                        getattr(struct_type, member).size,
                        (
                            f'    printf("{name}.{member} size:%zu\\n", '
                            f'sizeof(((struct {spec.c_name} *) 0)->{c_member}));',
                        ),
                    )
                )
    return checks


def c_probe(includes: Sequence[str], checks: Sequence[LayoutCheck]) -> str:
    lines = ['#include <stddef.h>', '#include <stdio.h>']
    lines += [f'#include <{include}>' for include in includes]
    lines += ['', 'int main(void) {']
    for check in checks:
        lines.extend(check.c_lines)
    lines += ['    return 0;', '}']
    return '\n'.join(lines)


def python_layout(checks: Sequence[LayoutCheck]) -> dict[str, int]:
    return {check.key: check.value for check in checks}


def parse_c_output(output: str) -> dict[str, int]:
    result = {}
    for line in output.splitlines():
        key, value = line.rsplit(':', 1)
        result[key] = int(value)
    return result


def compile_and_run(
    source: str,
    *,
    compiler: str,
    cflags: Sequence[str] = (),
    verbose: bool = False,
) -> str:
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / 'probe.c'
        executable = Path(directory) / 'probe'
        source_path.write_text(source)

        command = [compiler, *cflags, str(source_path), '-o', str(executable)]
        if verbose:
            print(f"Compiling with: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True)
        result.check_returncode()

        if verbose:
            preprocessed = subprocess.run(
                [compiler, '-E', *cflags, str(source_path)],
                capture_output=True,
                text=True,
            )
            preprocessed.check_returncode()
            for line in preprocessed.stdout.splitlines():
                if line and not line.startswith('#'):
                    print(line)

        return subprocess.check_output([str(executable)], text=True)


def format_layout_diff(python_layout: dict[str, int], c_layout: dict[str, int]) -> str:
    mismatches = []
    for key in sorted(set(python_layout) | set(c_layout)):
        python_value = python_layout.get(key)
        c_value = c_layout.get(key)
        if python_value != c_value:
            mismatches.append((key, c_value, python_value))

    lines = [f"  {key}: C={c_value}, Python={python_value}" for key, c_value, python_value in mismatches]
    if any(key.endswith('.size') for key, _, _ in mismatches):
        lines.append(
            "  A struct size mismatch with matching offsets usually means a trailing field is missing from the Python model."
        )
    return '\n'.join(lines)
