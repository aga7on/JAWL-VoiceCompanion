"""Resumable parallel HF range downloader for bounded model artifacts."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_chunk(url: str, start: int, end: int, path: Path, retries: int = 6) -> None:
    expected = end - start + 1
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(
                url,
                headers={
                    "Range": f"bytes={start}-{end}",
                    "Accept-Encoding": "identity",
                    "User-Agent": "JAWL-gemma4-probe/1.0",
                },
                stream=True,
                timeout=(15, 120),
            )
            if response.status_code != 206:
                raise RuntimeError(f"HTTP {response.status_code} for range {start}-{end}")
            written = 0
            with path.open("wb") as handle:
                for block in response.iter_content(1024 * 1024):
                    if block:
                        handle.write(block)
                        written += len(block)
            if written != expected:
                raise RuntimeError(f"short chunk {written}/{expected}")
            return
        except Exception as exc:  # noqa: BLE001 - retry transient HF/CDN failures
            last_error = exc
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(min(20, 2 + attempt * 2))
    raise RuntimeError(f"chunk {start}-{end} failed after {retries} attempts: {last_error}")


def download(url: str, out: Path, size: int, expected_sha: str, *, chunk_mb: int, workers: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file() and out.stat().st_size == size:
        if not expected_sha or sha256(out) == expected_sha:
            print(f"already complete: {out}")
            return
        raise RuntimeError(f"existing file has wrong SHA: {out}")
    parts = out.parent / (out.name + ".parts")
    if parts.exists():
        shutil.rmtree(parts)
    parts.mkdir(parents=True)
    chunk = max(1, int(chunk_mb)) * 1024 * 1024
    ranges = [(start, min(size - 1, start + chunk - 1)) for start in range(0, size, chunk)]
    print(f"download {out.name}: {size} bytes, {len(ranges)} chunks, {workers} workers", flush=True)
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {
            pool.submit(download_chunk, url, start, end, parts / f"part-{index:05d}"): (start, end)
            for index, (start, end) in enumerate(ranges)
        }
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed % 10 == 0 or completed == len(ranges):
                print(f"  {completed}/{len(ranges)} chunks", flush=True)
    temp = out.with_suffix(out.suffix + ".assembling")
    with temp.open("wb") as target:
        for index in range(len(ranges)):
            with (parts / f"part-{index:05d}").open("rb") as source:
                shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
    if temp.stat().st_size != size:
        raise RuntimeError(f"assembled size {temp.stat().st_size} != {size}")
    temp.replace(out)
    shutil.rmtree(parts)
    actual = sha256(out)
    if expected_sha and actual != expected_sha.lower():
        raise RuntimeError(f"SHA256 mismatch for {out}: {actual}")
    print(f"complete: {out} sha256={actual}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--size", required=True, type=int)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--chunk-mb", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    download(
        args.url,
        Path(args.out),
        args.size,
        args.sha256,
        chunk_mb=args.chunk_mb,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
