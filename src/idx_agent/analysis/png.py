"""WO-017 structural PNG check for renderer output; standard library only.

The host never decodes the picture with an image library. It walks the chunks
(signature, every CRC, a 13-byte IHDR first) and accepts only the layout the fixed
renderer writes: IHDR, an optional 9-byte pHYs, consecutive IDAT chunks, then an
empty IEND last. Nothing else may ride along, so the file has no room for text. The
header is pinned to 8-bit RGBA, not interlaced, within fixed bounds, and the joined
IDAT data must inflate with zlib to exactly the expected scanline bytes, each row
starting with a legal filter byte: a decompression bomb or a garbage stream fails.
"""

from __future__ import annotations

import struct
import zlib

from idx_agent.domain.analysis_worker import RENDER_STDOUT_CAP

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIN_WIDTH, MAX_WIDTH = 200, 2000
MIN_HEIGHT, MAX_HEIGHT = 150, 1500
# Exactly what matplotlib's Agg backend writes; every other chunk type is refused.
ALLOWED_CHUNKS: frozenset[bytes] = frozenset({b"IHDR", b"pHYs", b"IDAT", b"IEND"})
BIT_DEPTH, COLOUR_TYPE, CHANNELS = 8, 6, 4  # 8-bit RGBA
_PHYS_LENGTH = 9
_MAX_CHUNK = 1 << 31  # PNG chunk lengths are below 2**31
_MAX_FILTER = 4  # None, Sub, Up, Average, Paeth


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
    idat: list[bytes] = []
    previous = b""
    seen_phys = False
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
        offset += 12 + length
        if not previous:
            if kind != b"IHDR" or length != 13:
                return None
            size = _header(body)
            if size is None:
                return None
        elif kind == b"IHDR":
            return None
        elif kind == b"pHYs":
            if seen_phys or idat or length != _PHYS_LENGTH or body[8] > 1:
                return None  # once, before the image data, unit 0 or 1
            seen_phys = True
        elif kind == b"IDAT":
            if idat and previous != b"IDAT":
                return None  # image data chunks must be consecutive
            idat.append(body)
        elif kind == b"IEND":
            if length != 0 or not idat or offset != len(data):
                return None  # IEND must be empty, after the data, and last
            if size is None or not _scanlines_ok(b"".join(idat), *size):
                return None
            return size
        previous = kind


def _header(body: bytes) -> tuple[int, int] | None:
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", body
    )
    if not (MIN_WIDTH <= width <= MAX_WIDTH and MIN_HEIGHT <= height <= MAX_HEIGHT):
        return None
    if (depth, colour) != (BIT_DEPTH, COLOUR_TYPE):
        return None
    if compression != 0 or filtering != 0 or interlace != 0:
        return None
    return width, height


def _scanlines_ok(stream: bytes, width: int, height: int) -> bool:
    """The zlib stream inflates to exactly height rows of (filter byte + pixels)."""
    row = 1 + width * CHANNELS * BIT_DEPTH // 8
    expected = height * row
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(stream, expected + 1)  # never more than this
    except zlib.error:
        return False
    if len(raw) != expected or not inflater.eof:
        return False
    if inflater.unused_data or inflater.unconsumed_tail:
        return False
    return all(raw[start] <= _MAX_FILTER for start in range(0, expected, row))


def check_png(data: object, max_bytes: int = RENDER_STDOUT_CAP) -> bool:
    """True only for a bounded PNG in the renderer's exact layout, with no extras."""
    return png_size(data, max_bytes) is not None
