"""Fetch one source-deduplicated fold from the CC BY ESC-10 subset only."""
from __future__ import annotations

import argparse
import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
METADATA_URL = "https://raw.githubusercontent.com/karolpiczak/ESC-50/master/meta/esc50.csv"
AUDIO_URL = "https://raw.githubusercontent.com/karolpiczak/ESC-50/master/audio/{}"
FIELDS = ("fold", "category", "filename", "src_file", "take")


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "JAWL-local-audio-research/1.0"})
    last_error = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed after retries: {url}") from last_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold", type=int, choices=range(1, 6), required=True)
    args = parser.parse_args()
    rows = list(csv.DictReader(fetch(METADATA_URL).decode("utf-8").splitlines()))
    chosen: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if row.get("esc10") != "True" or row.get("fold") != str(args.fold):
            continue
        chosen.setdefault((row["category"], row["src_file"]), {field: row[field] for field in FIELDS})
    if not chosen:
        raise RuntimeError(f"ESC-10 fold {args.fold} contains no clips")

    target = ROOT / f"runtime/audio-path-replay/esc10-fold{args.fold}"
    target.mkdir(parents=True, exist_ok=True)
    manifest = target / "manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(chosen.values())

    def download(row: dict[str, str]) -> str:
        filename = row["filename"]
        path = target / filename
        if not path.is_file():
            path.write_bytes(fetch(AUDIO_URL.format(filename)))
        return filename

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(download, row) for row in chosen.values()]
        downloaded = [future.result() for future in as_completed(futures)]
    print(f"ESC-10 CC BY fold {args.fold}: {len(downloaded)} source-deduplicated clips, "
          f"{len({row['category'] for row in chosen.values()})} classes")
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
