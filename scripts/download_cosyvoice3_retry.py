"""Resumable CosyVoice3 download with bounded retry and quiet progress log."""

from __future__ import annotations

import time
from pathlib import Path

from modelscope import snapshot_download


TARGET = Path(r"G:\AI\CozyVoice\pretrained_models\Fun-CosyVoice3-0.5B")
REQUIRED = {
    "llm.pt": 1_500_000_000,
    "flow.pt": 1_000_000_000,
    "hift.pt": 70_000_000,
    "speech_tokenizer_v3.onnx": 800_000_000,
    "campplus.onnx": 20_000_000,
    "cosyvoice3.yaml": 1_000,
}


def complete() -> bool:
    return all((TARGET / name).exists() and (TARGET / name).stat().st_size >= size for name, size in REQUIRED.items())


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 51):
        if complete():
            print("COMPLETE", flush=True)
            return 0
        print(f"ATTEMPT {attempt}/50", flush=True)
        try:
            snapshot_download(
                "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                local_dir=str(TARGET),
            )
        except Exception as exc:  # network/download errors are retryable
            print(f"RETRYABLE_ERROR {type(exc).__name__}: {exc}", flush=True)
            time.sleep(15)
    print("INCOMPLETE_AFTER_RETRIES", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
