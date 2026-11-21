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
    member_types: bool = False

    @property
    def name(self) -> str:
        return self.key if self.key is not None else self.python_name


@dataclass(frozen=True)
class LayoutCheck:
    key: str
    value: int
    c_lines: tuple[str, ...]


# ctypes aliases several platform-dependent C types to the same Python class, so an exact type name
# cannot be recovered from the ctypes type alone. Keep offset and size checks for those members.
_AMBIGUOUS_C_TYPES = {
    ctypes.c_long,
    ctypes.c_ulong,
    ctypes.c_longlong,
    ctypes.c_ulonglong,
    ctypes.c_int64,
    ctypes.c_uint64,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
}


def _is_ambiguous_type(ctype) -> bool:
    if ctype in _AMBIGUOUS_C_TYPES:
        return True
    pointee = getattr(ctype, '_type_', None)
    return pointee is not None and _is_ambiguous_type(pointee)


MEMBER_TYPE_SKIP_STRUCTS = {'fuse_operations'}
MEMBER_TYPE_SKIPS = {
    ('c_stat', 'st_atimespec'),
    ('c_stat', 'st_mtimespec'),
    ('c_stat', 'st_ctimespec'),
    # macFUSE models the anonymous enable bitfield struct as a uint32 for the layout checks.
    ('fuse_conn_info', 'enable'),
}
# Some members intentionally use an ABI-compatible ctypes type instead of the exact typedef.
MEMBER_TYPE_OVERRIDES = {
    ('fuse_buf', 'flags'): 'enum fuse_buf_flags',
    ('fuse_config', 'flags'): 'uint32_t',
    ('fuse_context', 'fuse'): 'struct fuse *',
    ('fuse_conn_info', 'capable_ext'): 'uint64_t',
    ('fuse_conn_info', 'want_ext'): 'uint64_t',
    ('fuse_file_info', 'fh'): 'uint64_t',
    ('fuse_file_info', 'lock_owner'): 'uint64_t',
}


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
            type_lines = []
            if spec.member_types and spec.python_name not in MEMBER_TYPE_SKIP_STRUCTS:
                field_type = next((field[1] for field in fields if len(field) == 2 and field[0] == member), None)
                if (
                    field_type is not None
                    and (spec.python_name, member) not in MEMBER_TYPE_SKIPS
                    and not (isinstance(field_type, type) and issubclass(field_type, ctypes.Array))
                    and not (hasattr(field_type, '_argtypes_') and hasattr(field_type, '_restype_'))
                ):
                    c_type = MEMBER_TYPE_OVERRIDES.get((spec.python_name, member))
                    if c_type is None and not _is_ambiguous_type(field_type):
                        try:
                            c_type = c_type_name(field_type)
                        except AssertionError:
                            c_type = None
                    if c_type is not None:
                        type_lines.append(
                            f'    _Static_assert(MFUSEPY_SAME_TYPE(((struct {spec.c_name} *) 0)->{c_member}, '
                            f'{c_type}), "{name}.{member} type");'
                        )
            checks.append(
                LayoutCheck(
                    f'{name}.{member} offset',
                    getattr(struct_type, member).offset,
                    (
                        f'    printf("{name}.{member} offset:%zu\\n", offsetof(struct {spec.c_name}, {c_member}));',
                        *type_lines,
                    ),
                )
            )
            if spec.member_sizes and member not in spec.skip_member_sizes:
                checks.append(
                    LayoutCheck(
                        f'{name}.{member} size',
                        getattr(struct_type, member).size,
                        (
                            (
                                f'    printf("{name}.{member} size:%zu\\n", '
                                f'sizeof(((struct {spec.c_name} *) 0)->{c_member}));'
                            ),
                        ),
                    )
                )
    return checks


_PRIMITIVE_C_NAMES = {
    ctypes.c_char: 'char',
    ctypes.c_byte: 'char',
    ctypes.c_ubyte: 'unsigned char',
    ctypes.c_short: 'short',
    ctypes.c_ushort: 'unsigned short',
    ctypes.c_int: 'int',
    ctypes.c_uint: 'unsigned int',
    ctypes.c_long: 'long',
    ctypes.c_ulong: 'unsigned long',
    ctypes.c_longlong: 'long long',
    ctypes.c_ulonglong: 'unsigned long long',
    ctypes.c_int32: 'int32_t',
    ctypes.c_uint32: 'uint32_t',
    ctypes.c_int64: 'int64_t',
    ctypes.c_uint64: 'uint64_t',
    ctypes.c_size_t: 'size_t',
    ctypes.c_ssize_t: 'ssize_t',
}


def c_type_name(ctype, fuse_prefix: bool = False) -> str:
    if ctype is None or ctype is type(None):
        return 'void'
    if ctype is ctypes.c_char_p:
        return 'char *'
    if ctype is ctypes.c_void_p:
        return 'void *'
    if ctype is ctypes.c_size_t:
        return 'size_t'
    if ctype is ctypes.c_ssize_t:
        return 'ssize_t'
    if ctype in _PRIMITIVE_C_NAMES:
        return _PRIMITIVE_C_NAMES[ctype]
    pointee = getattr(ctype, '_type_', None)
    if pointee is not None:
        return f'{c_type_name(pointee, fuse_prefix)} *'
    if hasattr(ctype, '_argtypes_') and hasattr(ctype, '_restype_'):
        return 'fuse_fill_dir_t'
    name = getattr(ctype, '__name__', '')
    if name.startswith('c_'):
        c_name = name[2:]
        c_name = c_name.removesuffix('_t')
        return f'struct {"fuse_" if fuse_prefix else ""}{c_name}'
    if name.startswith('fuse_'):
        return f'struct {name}'
    raise AssertionError(f'No C type name known for {ctype!r}')


# ctypes aliases c_uint64 to c_ulong on LP64, so bmap's uint64_t * would otherwise be rendered as
# size_t *, which is incompatible with the Darwin headers.
_CALLBACK_ARGUMENT_NAMES = {
    ('bmap', 2): 'uint64_t *',
}


def function_prototype_checks(types, fuse_prefix: bool = False) -> list[str]:
    operations = getattr(types, 'fuse_operations', None)
    if operations is None:
        return []

    lines = ['static void check_fuse_operations(struct fuse_operations * operations) {']
    for field in operations._fields_:
        if len(field) != 2:
            continue
        name, callback = field
        if not hasattr(callback, '_argtypes_'):
            continue
        arguments = ', '.join(
            f'({_CALLBACK_ARGUMENT_NAMES.get((name, index), c_type_name(argument, fuse_prefix))}) 0'
            for index, argument in enumerate(callback._argtypes_)
        )
        return_type = c_type_name(callback._restype_, fuse_prefix)
        if return_type == 'void':
            lines.append(f'    operations->{name}({arguments});')
        else:
            lines.append(f'    {return_type} result_{name} = operations->{name}({arguments});')
            lines.append(
                f'    _Static_assert(MFUSEPY_SAME_TYPE(operations->{name}({arguments}), {return_type}), '
                f'"{name} return type");'
            )
            lines.append(f'    (void) result_{name};')
    lines += ['}', '']
    return lines


def c_probe(
    includes: Sequence[str],
    checks: Sequence[LayoutCheck],
    extra_declarations: Sequence[str] = (),
    extra_main_lines: Sequence[str] = (),
) -> str:
    lines = [
        '#include <stddef.h>',
        '#include <stdio.h>',
        '/* GCC and Clang can compare exact types. Other compilers fall back to a width check. */',
        '#if defined(__clang__) || defined(__GNUC__)',
        '#define MFUSEPY_SAME_TYPE(expression, type) __builtin_types_compatible_p(__typeof__(expression), type)',
        '#else',
        '#define MFUSEPY_SAME_TYPE(expression, type) (sizeof(expression) == sizeof(type))',
        '#endif',
    ]
    lines += [f'#include <{include}>' for include in includes]
    lines += list(extra_declarations)
    lines += ['', 'int main(void) {']
    for check in checks:
        lines.extend(check.c_lines)
    lines += list(extra_main_lines)
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
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        result.check_returncode()

        if verbose:
            preprocessed = subprocess.run(
                [compiler, '-E', *cflags, str(source_path)],
                capture_output=True,
                text=True,
                check=False,
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
            "  A struct size mismatch with matching offsets usually means a trailing field is missing "
            "from the Python model."
        )
    return '\n'.join(lines)
