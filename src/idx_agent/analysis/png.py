"""WO-017 structural PNG check for renderer output; standard library only.

The host never decodes the image. It walks the chunks: signature, IHDR first and
sane, every CRC, an allowlist of types (no text), IDAT, IEND last, fixed bounds.
"""

from __future__ import annotations

import struct
import zlib

from idx_agent.domain.analysis_worker import RENDER_STDOUT_CAP

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIN_WIDTH, MAX_WIDTH = 200, 2000
MIN_HEIGHT, MAX_HEIGHT = 150, 1500
ALLOWED_CHUNKS: frozenset[bytes] = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"pHYs",
        b"sRGB",
        b"gAMA",
        b"cHRM",
        b"iCCP",
        b"bKGD",
    }
)
# Colour type -> allowed bit depths (PNG specification, section 11.2.2).
_DEPTHS: dict[int, frozenset[int]] = {
    0: frozenset({1, 2, 4, 8, 16}),
    2: frozenset({8, 16}),
    3: frozenset({1, 2, 4, 8}),
    4: frozenset({8, 16}),
    6: frozenset({8, 16}),
}
_MAX_CHUNK = 1 << 31  # PNG chunk lengths are below 2**31


def png_size(
    data: object, max_bytes: int = RENDER_STDOUT_CAP
) -> tuple[int, int] | None:
    """(width, height) of a structurally valid PNG within the bounds, else None."""
    limit = min(max_bytes, RENDER_STDOUT_CAP)  # a caller may lower the cap only
    if not isinstance(data, bytes) or not 0 < len(data) <= limit:
        return None
    if not data.startswith(SIGNATURE):
        return None
    offset = len(SIGNATURE)
    size: tuple[int, int] | None = None
    seen_idat = False
    first = True
    while True:
        if offset + 12 > len(data):
            return None  # truncated: no room for a chunk header and CRC
        length, kind = struct.unpack(">I4s", data[offset : offset + 8])
        if length >= _MAX_CHUNK or offset + 12 + length > len(data):
            return None
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            return None
        if kind not in ALLOWED_CHUNKS:
            return None
        if first:
            if kind != b"IHDR" or length != 13:
                return None
            size = _header(body)
            if size is None:
                return None
            first = False
        elif kind == b"IHDR":
            return None
        offset += 12 + length
        if kind == b"IDAT":
            seen_idat = True
        if kind == b"IEND":
            if length != 0 or not seen_idat or offset != len(data):
                return None  # IEND must be empty, after the data, and last
            return size


def _header(body: bytes) -> tuple[int, int] | None:
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", body
    )
    if not (MIN_WIDTH <= width <= MAX_WIDTH and MIN_HEIGHT <= height <= MAX_HEIGHT):
        return None
    if depth not in _DEPTHS.get(colour, frozenset()):
        return None
    if compression != 0 or filtering != 0 or interlace not in (0, 1):
        return None
    return width, height


def check_png(data: object, max_bytes: int = RENDER_STDOUT_CAP) -> bool:
    """True only for a structurally valid, bounded PNG with no text chunks."""
    return png_size(data, max_bytes) is not None
