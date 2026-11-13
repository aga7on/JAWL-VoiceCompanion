"""Read the MTP/nextn metadata keys from a GGUF file."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

SCALARS = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2),
    4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1),
    10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8),
}


def read_str(f) -> str:
    length = struct.unpack("<Q", f.read(8))[0]
    return f.read(length).decode("utf-8", "replace")


def skip_value(f, t) -> None:
    if t in SCALARS:
        f.read(SCALARS[t][1])
    elif t == 8:
        length = struct.unpack("<Q", f.read(8))[0]
        f.read(length)
    elif t == 9:
        item = struct.unpack("<I", f.read(4))[0]
        count = struct.unpack("<Q", f.read(8))[0]
        for _ in range(count):
            skip_value(f, item)
    else:
        raise ValueError(f"unknown gguf type {t}")


def read_value(f, t):
    if t in SCALARS:
        fmt, size = SCALARS[t]
        return struct.unpack(fmt, f.read(size))[0]
    if t == 8:
        return read_str(f)
    if t == 9:
        item = struct.unpack("<I", f.read(4))[0]
        count = struct.unpack("<Q", f.read(8))[0]
        if count > 50_000:
            for _ in range(count):
                skip_value(f, item)
            return f"<array of {count}>"
        return [read_value(f, item) for _ in range(count)]
    raise ValueError(t)


def main() -> int:
    model = Path(sys.argv[1])
    with model.open("rb") as f:
        f.read(4)
        struct.unpack("<I", f.read(4))
        struct.unpack("<Q", f.read(8))
        n_kv = struct.unpack("<Q", f.read(8))[0]
        for _ in range(n_kv):
            key = read_str(f)
            value_type = struct.unpack("<I", f.read(4))[0]
            if any(token in key.lower() for token in ("nextn", "mtp", "block_count", "expert_feed_forward")):
                try:
                    print(f"{key} = {read_value(f, value_type)}")
                except ValueError:
                    skip_value(f, value_type)
            else:
                skip_value(f, value_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())