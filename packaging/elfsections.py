"""Read one section out of a 64-bit little-endian ELF file.

The AppImage build needs to look inside the finished image for the update
information appimagetool embedded. `readelf -x` prints the bytes as a hex dump,
so the string would be split across its ASCII column; reading the section header
directly is both exact and free of external tools.
"""

from __future__ import annotations

import struct
from pathlib import Path

_ELF_MAGIC = b"\x7fELF"
_ELFCLASS64 = 2
_ELFDATA2LSB = 1


class ElfError(RuntimeError):
    """The file is not a 64-bit little-endian ELF."""


def read_section(path: Path, name: str) -> bytes | None:
    """The bytes of section `name`, or None when the section is absent."""
    with path.open("rb") as handle:
        ident = handle.read(16)
        if (
            ident[:4] != _ELF_MAGIC
            or ident[4] != _ELFCLASS64
            or ident[5] != _ELFDATA2LSB
        ):
            raise ElfError(f"{path} is not a 64-bit little-endian ELF")

        handle.seek(0x28)
        table_offset = struct.unpack("<Q", handle.read(8))[0]
        handle.seek(0x3A)
        entry_size, count, names_index = struct.unpack("<HHH", handle.read(6))
        if table_offset == 0 or count == 0:
            return None

        def header(index: int) -> tuple[int, int, int]:
            handle.seek(table_offset + index * entry_size)
            raw = handle.read(entry_size)
            if len(raw) < 0x28:
                raise ElfError(f"{path} has a truncated section header table")
            name_offset = struct.unpack_from("<I", raw, 0)[0]
            offset, size = struct.unpack_from("<QQ", raw, 0x18)
            return name_offset, offset, size

        _, names_offset, names_size = header(names_index)
        handle.seek(names_offset)
        names = handle.read(names_size)

        for index in range(count):
            name_offset, offset, size = header(index)
            end = names.find(b"\x00", name_offset)
            if end < 0:
                continue
            if names[name_offset:end].decode("ascii", "replace") != name:
                continue
            handle.seek(offset)
            return handle.read(size)
    return None
