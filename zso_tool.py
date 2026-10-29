#!/usr/bin/env python3
"""
Compress PS2 ISOs to ZSO, the format OPL, PCSX2 and maxcso share.

The file is ZISO version 1: a 24-byte header, an index of block_count + 1
32-bit entries, then each 2048-byte sector compressed on its own with
LZ4 (high compression). An index entry holds the block's file offset
shifted right by `align`; its top bit marks a block stored uncompressed
because LZ4 could not make it smaller. Blocks start on 1 << align byte
boundaries, so a file past 2 GiB still fits 31-bit index entries.

Every file is checked after writing: it is decompressed again and its MD5
compared with the ISO's, and only then given its final name. With
delete_original the ISO is removed after that check.

Usage:
    python zso_tool.py GAME.iso [GAME2.iso ...]        writes GAME.zso
    python zso_tool.py --delete-original E:/PS2/DVD/*.iso
"""

import hashlib
import os
import struct
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import lz4.block

MAGIC = b"ZISO"
HEADER_SIZE = 24
BLOCK = 2048
VERSION = 1
STORED = 0x80000000
CHUNK_BLOCKS = 512          # 1 MiB per work item
LZ4_LEVEL = 9               # LZ4 HC; 12 is barely smaller and much slower
THREADS = max(1, min(8, (os.cpu_count() or 2)))


class Cancelled(Exception):
    pass


class NotWorthIt(Exception):
    """The ZSO came out (almost) as big as the ISO; it was removed and the
    ISO kept."""


def _align_shift(size):
    """Smallest shift that keeps the largest possible offset in 31 bits."""
    blocks = (size + BLOCK - 1) // BLOCK
    shift = 0
    while True:
        worst = HEADER_SIZE + (blocks + 1) * 4 + size + blocks * ((1 << shift) - 1) + (1 << shift)
        if (worst >> shift) < STORED:
            return shift
        shift += 1


def _compress_chunk(data):
    """Compress each 2048-byte block of data. LZ4 releases the GIL, so
    chunks compress in parallel on threads."""
    out = []
    for i in range(0, len(data), BLOCK):
        block = data[i:i + BLOCK]
        packed = lz4.block.compress(block, mode="high_compression", compression=LZ4_LEVEL, store_size=False)
        if len(packed) >= len(block):
            out.append((True, block))
        else:
            out.append((False, packed))
    return out


def compress_iso(src, dst=None, progress=None, cancel=None, delete_original=False, min_saving=0.01):
    """Compress src (an .iso) to dst (default: same name, .zso).

    progress(done_bytes, total_bytes, phase) is called now and then, phase
    "compress" or "verify". cancel is a threading.Event. Returns
    (iso_bytes, zso_bytes). Raises Cancelled, NotWorthIt (saving below
    min_saving: ZSO removed, ISO kept), or OSError/ValueError.
    """
    if dst is None:
        dst = os.path.splitext(src)[0] + ".zso"
    part = dst + ".part"
    size = os.path.getsize(src)
    if size == 0:
        raise ValueError("empty file")
    blocks = (size + BLOCK - 1) // BLOCK
    shift = _align_shift(size)
    pad_to = 1 << shift
    index = []
    md5_src = hashlib.md5()

    def check():
        if cancel is not None and cancel.is_set():
            raise Cancelled()

    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            fout.write(struct.pack("<4sIQIBB2x", MAGIC, HEADER_SIZE, size, BLOCK, VERSION, shift))
            fout.write(b"\0" * ((blocks + 1) * 4))
            pos = HEADER_SIZE + (blocks + 1) * 4
            done = 0

            with ThreadPoolExecutor(THREADS) as pool:
                pending = []

                def drain(fut):
                    nonlocal pos
                    for stored, data in fut.result():
                        if pos % pad_to:
                            pad = pad_to - pos % pad_to
                            fout.write(b"\0" * pad)
                            pos += pad
                        index.append((pos >> shift) | (STORED if stored else 0))
                        fout.write(data)
                        pos += len(data)

                while True:
                    check()
                    data = fin.read(CHUNK_BLOCKS * BLOCK)
                    if not data:
                        break
                    md5_src.update(data)
                    pending.append(pool.submit(_compress_chunk, data))
                    done += len(data)
                    # Keep a few chunks in flight, write them in order.
                    while len(pending) > THREADS * 2:
                        drain(pending.pop(0))
                    if progress:
                        progress(done, size, "compress")
                for fut in pending:
                    check()
                    drain(fut)

            if pos % pad_to:
                pad = pad_to - pos % pad_to
                fout.write(b"\0" * pad)
                pos += pad
            index.append(pos >> shift)
            if len(index) != blocks + 1:
                raise ValueError("block count mismatch")
            fout.seek(HEADER_SIZE)
            fout.write(struct.pack(f"<{len(index)}I", *index))
            fout.flush()
            os.fsync(fout.fileno())

        _verify(part, size, md5_src.digest(), progress, check)
        os.replace(part, dst)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise

    zsize = os.path.getsize(dst)
    if zsize > size * (1 - min_saving):
        os.remove(dst)
        raise NotWorthIt()
    if delete_original:
        os.remove(src)
    return size, zsize


def _verify(path, size, digest, progress, check):
    """Decompress path the way a reader does and compare with the ISO."""
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        hdr = f.read(HEADER_SIZE)
        magic, hsize, total, bsize, ver, shift = struct.unpack("<4sIQIBB2x", hdr)
        if magic != MAGIC or total != size or bsize != BLOCK:
            raise ValueError("bad header written")
        blocks = (size + BLOCK - 1) // BLOCK
        f.seek(hsize)
        idx = struct.unpack(f"<{blocks + 1}I", f.read((blocks + 1) * 4))
        done = 0
        for b in range(blocks):
            if b % 4096 == 0:
                check()
                if progress:
                    progress(done, size, "verify")
            start = (idx[b] & 0x7FFFFFFF) << shift
            end = (idx[b + 1] & 0x7FFFFFFF) << shift
            f.seek(start)
            raw = f.read(end - start)
            want = min(BLOCK, size - b * BLOCK)
            if idx[b] & STORED:
                data = raw[:want]
            else:
                data = None
                # Trailing alignment padding: the same retry OPL does.
                for cut in range(0, min(len(raw), 1 << shift)):
                    try:
                        data = lz4.block.decompress(raw[:len(raw) - cut] if cut else raw, uncompressed_size=want)
                        break
                    except lz4.block.LZ4BlockError:
                        continue
                if data is None or len(data) != want:
                    raise ValueError(f"block {b} does not decompress")
            md5.update(data)
            done += want
    if md5.digest() != digest:
        raise ValueError("verification failed: data differs from the ISO")
    if progress:
        progress(size, size, "verify")


def main(argv):
    delete = "--delete-original" in argv
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    total_in = total_out = 0
    for src in files:
        print(f"{src} ...", flush=True)

        def prog(done, total, phase, _last=[0]):
            pct = done * 100 // total
            if pct != _last[0]:
                _last[0] = pct
                print(f"\r  {phase} {pct:3d}%", end="", flush=True)

        try:
            a, b = compress_iso(src, progress=prog, delete_original=delete)
        except NotWorthIt:
            print("\r  does not compress; ISO kept")
            continue
        except (OSError, ValueError) as e:
            print(f"\r  failed: {e}")
            continue
        total_in += a
        total_out += b
        print(f"\r  {a / 2**20:.0f} MB -> {b / 2**20:.0f} MB ({100 * b // a}%)")
    if total_in:
        print(f"saved {(total_in - total_out) / 2**30:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
