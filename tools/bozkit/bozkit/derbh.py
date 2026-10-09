"""Read single files from the game's Derbh (``.dz``) packs without extracting them.

Format as documented by dade (tools/destin, ``dade.marmalade.derbh``, MIT)::

    "DTRZ", u16 file_count, u16 folder_count (with the root), u8 0
    cstr[file_count] file names, cstr[folder_count - 1] folder paths ('\\' separators)
    file_count x (u16 folder, u16 file_no, u16 flags)
    a short header, then file_count (+1) x (u32 offset, u32 size_a, u32 size_b, u32 method)
    data: method 0x100 stored, 0x200 LZMA-alone, 0x8 gzip (trailer CRC is wrong; inflate raw)

bozkit only needs a few groups out of a 400 MB pack, so :class:`Pack` maps the file and
decompresses entries on demand.
"""
from __future__ import annotations

import lzma
import mmap
import struct
import zlib
from pathlib import Path

MAGIC = b'DTRZ'
STORED, LZMA, GZIP = 0x100, 0x200, 0x8
_METHODS = frozenset((0x8, 0x100, 0x200, 0x300, 0x400))
_MAX_GAP = 0x1000
_SLACK = 0x20000


def _inflate_gzip(blob) -> bytes:
    flags, p = blob[3], 10
    if flags & 4:
        p += 2 + struct.unpack_from('<H', blob, p)[0]
    if flags & 8:
        p = bytes(blob[p:p + 4096]).index(b'\0') + p + 1
    if flags & 16:
        p = bytes(blob[p:p + 4096]).index(b'\0') + p + 1
    if flags & 2:
        p += 2
    inflater = zlib.decompressobj(wbits=-15)
    return inflater.decompress(blob[p:]) + inflater.flush()


class Pack:
    """A ``.dz`` archive: ``names()`` lists paths ('/' separated), ``read(path)`` returns bytes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with open(self.path, 'rb') as handle:
            self._data = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        data = self._data
        if data[:4] != MAGIC:
            raise ValueError(f'{self.path.name} is not a Derbh (.dz) archive')
        count, folder_count = struct.unpack_from('<HH', data, 4)
        p, names, folders = 9, [], ['']
        for _ in range(count):
            end = data.find(b'\0', p)
            names.append(data[p:end].decode('latin-1'))
            p = end + 1
        for _ in range(folder_count - 1):
            end = data.find(b'\0', p)
            folders.append(data[p:end].decode('latin-1').replace('\\', '/').strip('/'))
            p = end + 1
        folder_of = [struct.unpack_from('<H', data, p + i * 6)[0] for i in range(count)]
        records = self._locations(p + count * 6, count)
        self._entries: dict[str, tuple[int, int, int]] = {}
        for i, name in enumerate(names):
            folder = folders[folder_of[i]] if folder_of[i] < len(folders) else ''
            offset, size_a, size_b, method = records[i]
            path = f'{folder}/{name}' if folder else name
            self._entries[path.lower()] = (offset, size_b or size_a, method)

    def _locations(self, start: int, count: int) -> list[tuple[int, int, int, int]]:
        """The location table sits a few header bytes after the attribute table; find it as the
        first run of records whose offsets all point past it with known methods."""
        data, size = self._data, len(self._data)
        for records in (count + 1, count):
            for header in range(128):
                p = start + header
                end = p + records * 16
                if end > size:
                    continue
                table = [struct.unpack_from('<IIII', data, p + i * 16) for i in range(records)]
                if all(end <= o <= size and m in _METHODS for o, _, _, m in table) and \
                        end <= min(o for o, *_ in table) <= end + _MAX_GAP:
                    return table[:count]
        raise ValueError(f'{self.path.name}: location table not found')

    def names(self) -> list[str]:
        return sorted(self._entries)

    def __contains__(self, path: str) -> bool:
        return path.lower().strip('/') in self._entries

    def read(self, path: str) -> bytes:
        try:
            offset, size, method = self._entries[path.lower().strip('/')]
        except KeyError:
            raise KeyError(f'{path} is not in {self.path.name}') from None
        window = self._data[offset:min(offset + size + _SLACK, len(self._data))]
        if not window:
            return b''
        if method == STORED:
            return window[:size]
        if method == LZMA or (method not in (GZIP,) and window[0] == 0x5D):
            return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(window)[:size or None]
        if method == GZIP or window[:2] == b'\x1f\x8b':
            return _inflate_gzip(window)
        if window[0] == 0x78:
            return zlib.decompressobj().decompress(window)
        return window[:size]

    def close(self) -> None:
        self._data.close()
