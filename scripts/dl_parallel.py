"""Multi-threaded resumable downloader for Hugging Face safetensors via range requests.

HF's AWS CDN throttles a single connection (~140 KB/s) but parallel range
requests deliver ~500 KB/s per connection combined. We split the file into N
concurrent chunks, each curl --range resumes independently, then concatenate.

Usage: python -X utf8 scripts/dl_parallel.py <url> <out_file> [threads] [total_bytes]
  total_bytes optional: if given, we verify the final size; otherwise we fetch
  Content-Length via a HEAD request.
"""
from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import urllib.request

CHUNK_MB = 8  # each thread pulls 8 MB per invocation (short, low stall risk)


def content_length(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return int(resp.headers["Content-Length"])


def fetch_range(url: str, out: str, start: int, end: int) -> bool:
    tmp = f"{out}.part.{start}"
    if os.path.exists(tmp) and os.path.getsize(tmp) == end - start + 1:
        return True
    # resume from existing partial
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    args = ["curl.exe", "-sL", "--fail", "--retry", "8", "--retry-delay", "3",
            "-r", f"{start + have}-{end}", "-o", tmp, url]
    r = subprocess.run(args, capture_output=True, timeout=600)
    return r.returncode == 0


def main() -> int:
    url = sys.argv[1]
    out = sys.argv[2]
    threads = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    total = int(sys.argv[4]) if len(sys.argv) > 4 else content_length(url)
    print(f"total={total/1e6:.1f} MB threads={threads}")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    chunk = CHUNK_MB * 1024 * 1024
    ranges = [(s, min(s + chunk - 1, total - 1)) for s in range(0, total, chunk)]
    print(f"chunks={len(ranges)}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {ex.submit(fetch_range, url, out, s, e): s for s, e in ranges}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            done += 1
            if not fut.result():
                print(f"chunk failed: {futs[fut]}", file=sys.stderr)

    # concatenate in order; keep parts until the whole file is verified so a
    # single failed chunk never forces re-downloading the concatenated prefix.
    missing = [s for s, _ in ranges if not os.path.exists(f"{out}.part.{s}")]
    if missing:
        print(f"missing parts: {len(missing)} (first {missing[0]}) - rerun to resume", file=sys.stderr)
        return 2
    with open(out, "wb") as fh:
        for s, _ in ranges:
            with open(f"{out}.part.{s}", "rb") as p:
                while True:
                    block = p.read(8 * 1024 * 1024)
                    if not block:
                        break
                    fh.write(block)
    got = os.path.getsize(out)
    print(f"done: {got/1e6:.1f} MB (expected {total/1e6:.1f})")
    if got != total:
        print("SIZE MISMATCH — rerun to resume (parts kept)", file=sys.stderr)
        return 3
    for s, _ in ranges:
        os.remove(f"{out}.part.{s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())