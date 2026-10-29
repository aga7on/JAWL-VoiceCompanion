"""Download the pinned Gemma 4 E4B CPU experiment artifacts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from download_hf_ranges import download  # noqa: E402

MODELS = {
    "q2": [
        (
            "https://huggingface.co/unsloth/gemma-4-E4B-it-qat-mobile-GGUF/resolve/6a6e7121b977cefd85daa8fbc538fa485e7e8b1b/gemma-4-E4B-it-qat-UD-Q2_K_XL.gguf?download=true",
            ROOT / "runtime/gemma4-e4b-cpu/models/unsloth/gemma-4-E4B-it-qat-UD-Q2_K_XL.gguf",
            3219532192,
            "79dde517866cfbb5c00230b530de17910fc7fc78f8827554d0e14281ce5faf03",
        ),
        (
            "https://huggingface.co/unsloth/gemma-4-E4B-it-qat-mobile-GGUF/resolve/6a6e7121b977cefd85daa8fbc538fa485e7e8b1b/mmproj-F16.gguf?download=true",
            ROOT / "runtime/gemma4-e4b-cpu/models/unsloth/mmproj-F16.gguf",
            990372672,
            "6a255159ee4b01b304f633a57f017dd7d5a69d30fff52abb2614bf0813cef034",
        ),
    ],
    "q4": [
        (
            "https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/resolve/4b4a2c1d584be7264f87aac328a1bc739ce81b6c/gemma-4-E4B_q4_0-it.gguf?download=true",
            ROOT / "runtime/gemma4-e4b-cpu/models/google/gemma-4-E4B_q4_0-it.gguf",
            5154941280,
            "676c35070db6dbe52f93e9c864ee0fba4eddea94b9c875d9cb10daff453fbaee",
        ),
        (
            "https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/resolve/4b4a2c1d584be7264f87aac328a1bc739ce81b6c/gemma-4-E4B-it-mmproj.gguf?download=true",
            ROOT / "runtime/gemma4-e4b-cpu/models/google/gemma-4-E4B-it-mmproj.gguf",
            991552256,
            "7498a37cb619e55f2fcf87eb931f56e99389ed6d432e4c5c66110694c0d65578",
        ),
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quant", choices=["q2", "q4", "all"], default="q2")
    parser.add_argument("--chunk-mb", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    quant = args.quant
    names = ["q2", "q4"] if quant == "all" else [quant]
    for name in names:
        for url, out, size, sha in MODELS[name]:
            download(url, out, size, sha, chunk_mb=args.chunk_mb, workers=args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
