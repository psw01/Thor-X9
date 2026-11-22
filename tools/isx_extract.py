#!/usr/bin/env python3
"""Extract files from an InstallShield "ISSetupStream" setup.exe without running it.

Usage: python3 -I isx_extract.py Thor_X9_Software_V1.0_19122000.exe outdir/
Requires: pip install pefile

Format (as found in the Thor X9 installer):
  overlay header (0x2E bytes): "ISSetupStream\\0", u16 file count, u32 type, padding
  per file: u32 name_len, u32 flags, u16 ?, u32 data_len, 8 bytes ?, u16 ?,
            UTF-16LE name, data
  data: each byte b -> ~(key[i % len(key)] ^ rol4(b)), i restarting every 1024 bytes,
        key = ascii(name) XOR 13 35 86 07 (repeating); result is zlib-compressed.
Then: msiextract (msitools) unpacks the embedded .msi.
"""
import os
import struct
import sys
import zlib

import pefile

MAGIC = (0x13, 0x35, 0x86, 0x07)


def decode(data: bytes, name: str) -> bytes:
    key = bytes(c ^ MAGIC[i % 4] for i, c in enumerate(name.encode("latin-1")))
    out = bytearray(len(data))
    for i, c in enumerate(data):
        out[i] = ~(key[(i % 1024) % len(key)] ^ (((c << 4) | (c >> 4)) & 0xFF)) & 0xFF
    return bytes(out)


def main(src: str, outdir: str) -> None:
    off = pefile.PE(src, fast_load=True).get_overlay_data_start_offset()
    d = open(src, "rb").read()
    if d[off:off + 13] != b"ISSetupStream":
        sys.exit("not an ISSetupStream installer")
    count, = struct.unpack_from("<H", d, off + 14)
    p = off + 0x2E
    os.makedirs(outdir, exist_ok=True)
    for _ in range(count):
        name_len, _flags, _x, size = struct.unpack_from("<IIHI", d, p)
        p += 24
        name = d[p:p + name_len].decode("utf-16le")
        p += name_len
        raw = decode(d[p:p + size], name)
        p += size
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        dest = os.path.join(outdir, os.path.basename(name))
        with open(dest, "wb") as f:
            f.write(raw)
        print(f"{name}: {len(raw)} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
