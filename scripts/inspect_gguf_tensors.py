"""List tensor name patterns to understand what this model actually is."""
from __future__ import annotations

import struct
from collections import Counter
from pathlib import Path

MODEL = Path(__file__).resolve().parents[1] / "runtime" / "sensenova-loop" / "models" / \
    "SenseNova-Loop-9B-Preview-Q4_K_M-verified.gguf"

SCALARS = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2),
    4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1),
    10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8),
}


def read_str(f) -> str:
    ln = struct.unpack("<Q", f.read(8))[0]
    return f.read(ln).decode("utf-8", "replace")


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
            # Skip huge tokenizer arrays efficiently.
            for _ in range(count):
                read_value(f, item)
            return f"<array of {count}>"
        return [read_value(f, item) for _ in range(count)]
    raise ValueError(t)


def main() -> int:
    with MODEL.open("rb") as f:
        f.read(4)
        struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        for _ in range(n_kv):
            key = read_str(f)
            vtype = struct.unpack("<I", f.read(4))[0]
            read_value(f, vtype)

        names = []
        for _ in range(n_tensors):
            name = read_str(f)
            n_dims = struct.unpack("<I", f.read(4))[0]
            dims = [struct.unpack("<Q", f.read(8))[0] for _ in range(n_dims)]
            struct.unpack("<I", f.read(4))[0]  # ggml type
            struct.unpack("<Q", f.read(8))[0]  # offset
            names.append((name, dims))

    print(f"tensors: {len(names)}")
    print()
    # Group by tensor "kind" = name with layer index stripped.
    kinds: Counter[str] = Counter()
    for name, dims in names:
        parts = name.split(".")
        if len(parts) > 2 and parts[1].isdigit():
            kind = f"{parts[0]}.*.{'.'.join(parts[2:])}"
        else:
            kind = name
        kinds[kind] += 1
    for kind, count in kinds.most_common(30):
        print(f"  {count:4d}  {kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())