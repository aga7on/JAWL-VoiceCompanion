"""Read GGUF metadata for the brain model without loading weights."""
from __future__ import annotations

import struct
from pathlib import Path

MODEL = Path(__file__).resolve().parents[1] / "runtime" / "sensenova-loop" / "models" / \
    "SenseNova-Loop-9B-Preview-Q4_K_M-verified.gguf"

SCALARS = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2),
    4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1),
    10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8),
}
TYPE_STR, TYPE_ARR = 8, 9


def read_str(f) -> str:
    ln = struct.unpack("<Q", f.read(8))[0]
    if ln > 1_000_000:
        raise ValueError(f"implausible string length {ln}")
    return f.read(ln).decode("utf-8", "replace")


def read_value(f, t):
    if t in SCALARS:
        fmt, size = SCALARS[t]
        return struct.unpack(fmt, f.read(size))[0]
    if t == TYPE_STR:
        return read_str(f)
    if t == TYPE_ARR:
        item_type = struct.unpack("<I", f.read(4))[0]
        count = struct.unpack("<Q", f.read(8))[0]
        if count > 100_000:
            raise ValueError(f"implausible array count {count}")
        return [read_value(f, item_type) for _ in range(count)]
    raise ValueError(f"unknown gguf type {t}")


def main() -> int:
    with MODEL.open("rb") as f:
        if f.read(4) != b"GGUF":
            print("not a GGUF file")
            return 1
        version = struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        print(f"GGUF v{version}  tensors={n_tensors}  metadata={n_kv}")

        info: dict[str, object] = {}
        for _ in range(n_kv):
            key = read_str(f)
            value_type = struct.unpack("<I", f.read(4))[0]
            try:
                info[key] = read_value(f, value_type)
            except ValueError as exc:
                print(f"  (stopped at {key}: {exc})")
                break

    interesting = (
        "architecture", "block_count", "context_length", "embedding_length",
        "head_count", "head_count_kv", "expert", "file_type",
        "rope", "attention", "feed_forward", "layer_norm",
    )
    print()
    for key in sorted(info):
        if any(token in key.lower() for token in interesting):
            value = info[key]
            shown = value if not isinstance(value, list) else f"list[{len(value)}]"
            print(f"  {key} = {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())