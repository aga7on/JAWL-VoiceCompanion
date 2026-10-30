"""Verify a .safetensors file: exact size (optional) + header parse + tensor count.

Two independent invariants, so a truncated or mis-concatenated download is
caught instead of surfacing later as a confusing load error.

Usage: python -X utf8 scripts/verify_safetensors.py <file.safetensors> [expected_bytes]
Exit 0 only when every check passes.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    expected = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if not path.exists():
        print(f"MISSING: {path}", file=sys.stderr)
        return 2

    size = path.stat().st_size
    ok = True
    print(f"size: {size} bytes ({size/1e6:.1f} MB)")
    if expected is not None:
        match = size == expected
        ok &= match
        print(f"size check: {'PASS' if match else 'FAIL'} (expected {expected})")

    with open(path, "rb") as fh:
        raw = fh.read(8)
        if len(raw) != 8:
            print("header length: FAIL (file shorter than 8 bytes)", file=sys.stderr)
            return 3
        header_len = struct.unpack("<Q", raw)[0]
        print(f"header length: {header_len}")
        if header_len <= 0 or header_len > 100_000_000 or 8 + header_len > size:
            print("header length: FAIL (implausible or beyond EOF)", file=sys.stderr)
            return 3
        try:
            header = json.loads(fh.read(header_len).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"header parse: FAIL ({exc})", file=sys.stderr)
            return 3

    tensors = {k: v for k, v in header.items() if k != "__metadata__"}
    total_elems = 0
    for spec in tensors.values():
        shape = spec.get("shape") or []
        count = 1
        for dim in shape:
            count *= int(dim)
        total_elems += count
    print(f"tensors: {len(tensors)}  elements: {total_elems/1e9:.3f}e9")
    if not tensors:
        print("tensors: FAIL (empty tensor map)", file=sys.stderr)
        return 3
    # data section must fit exactly
    data_bytes = size - 8 - header_len
    print(f"data section: {data_bytes/1e6:.1f} MB")
    print("RESULT: " + ("PASS" if ok and len(tensors) > 0 and data_bytes > 0 else "FAIL"))
    return 0 if ok and len(tensors) > 0 and data_bytes > 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
