"""Content-vision benchmark: video-only frames, Qwen plain-text captions.

Single frame: one sentence, 64 tokens, retry at 128 if truncated.
Pairs: two consecutive frames in one request, same plain-text contract.
RAM/prompt cache is disabled so every image is processed again.
"""
from __future__ import annotations

import argparse
import base64
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import requests

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

SINGLE_PROMPT = (
    "Describe this video frame in one sentence. Name visible objects and "
    "actions. Do not transcribe on-screen text. Do not mention audio. "
    "Plain text only, no JSON."
)
PAIR_PROMPT = (
    "These are two consecutive video frames. In one sentence, describe what "
    "changed between them and name the visible objects and actions. Do not "
    "transcribe on-screen text. Do not mention audio. Plain text only, no JSON."
)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 1)


def _rss_mb(pid: int) -> float:
    try:
        process = psutil.Process(pid)
        total = 0
        for item in [process, *process.children(recursive=True)]:
            try:
                total += item.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return round(total / (1024 * 1024), 1)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def _stop_tree(pid: int) -> None:
    try:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except psutil.TimeoutExpired:
            process.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def _metrics(url: str) -> dict[str, float]:
    result: dict[str, float] = {}
    try:
        for line in requests.get(url + "/metrics", timeout=5).text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) == 2:
                try:
                    result[parts[0]] = float(parts[1])
                except ValueError:
                    pass
    except requests.RequestException:
        pass
    return result


def _delta(before: dict[str, float], after: dict[str, float], key: str) -> float:
    return round(max(0.0, after.get(key, 0.0) - before.get(key, 0.0)), 3)


def _request(url: str, model: str, images: list[Path], budget: int, pair: bool) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": PAIR_PROMPT if pair else SINGLE_PROMPT}]
    for image in images:
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": budget,
        "temperature": 0.0,
        "top_p": 0.9,
        "stream": True,
    }
    started = time.perf_counter()
    ttft = None
    text = ""
    finish_reason = None
    try:
        response = requests.post(url + "/chat/completions", json=payload, stream=True, timeout=240)
        if response.status_code >= 400:
            return {
                "status": "http_error",
                "error": response.text[:500],
                "ttft_ms": None,
                "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "budget": budget,
            }
        for raw in response.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            choice = (event.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                if ttft is None:
                    ttft = round((time.perf_counter() - started) * 1000.0, 1)
                text += piece
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "request_error",
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "ttft_ms": None,
            "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "budget": budget,
        }
    total = round((time.perf_counter() - started) * 1000.0, 1)
    stripped = text.strip()
    truncated = finish_reason == "length" or (
        bool(stripped) and not stripped.endswith((".", "!", "?")) and finish_reason is None
    )
    return {
        "status": "ok" if stripped else "empty",
        "caption": stripped,
        "finish_reason": finish_reason,
        "truncated": truncated,
        "ttft_ms": ttft,
        "total_ms": total,
        "generation_ms": round(total - (ttft or total), 1),
        "budget": budget,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/vlm-cpu-bench.json"))
    parser.add_argument("--frames", default=str(ROOT / "runtime/vlm-cpu-bench/video"))
    parser.add_argument("--out", default=str(ROOT / "runtime/vlm-cpu-bench/content/qwen3.5-0.8b.json"))
    parser.add_argument("--idle-seconds", type=float, default=20.0)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    cfg = next(model for model in config["models"] if model["id"] == "qwen3.5-0.8b")
    runtime = config["runtime"]
    frames = sorted(Path(args.frames).glob("frame-*.jpg"))
    if len(frames) != 12:
        raise SystemExit(f"expected 12 frames, found {len(frames)}")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir = out_path.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [
        runtime["llama_server"],
        "-m", cfg["file"],
        "--mmproj", cfg["mmproj"],
        "--host", "127.0.0.1",
        "--port", str(cfg["port"]),
        "-c", "4096",
        "-np", "1",
        "-t", "6",
        "-tb", "6",
        "--jinja",
        "--reasoning", "off",
        "-ngl", "0",
        "--no-mmproj-offload",
        "--metrics",
        "--cache-ram", "0",
        "--no-cache-prompt",
        "--no-cache-idle-slots",
    ]
    out_handle = (log_dir / "qwen3.5-0.8b-content.out.log").open("ab")
    err_handle = (log_dir / "qwen3.5-0.8b-content.err.log").open("ab")
    process = subprocess.Popen(
        command,
        cwd=str(Path(runtime["llama_server"]).parent),
        stdout=out_handle,
        stderr=err_handle,
    )
    url = f"http://127.0.0.1:{cfg['port']}"
    deadline = time.time() + 240
    ready = False
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            if requests.get(url + "/health", timeout=2).status_code == 200:
                ready = True
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    if not ready:
        tail = (log_dir / "qwen3.5-0.8b-content.err.log").read_text(encoding="utf-8", errors="replace")[-3000:]
        _stop_tree(process.pid)
        raise SystemExit(f"server failed: {tail}")
    cases: list[dict[str, Any]] = []
    rss_load = _rss_mb(process.pid)
    try:
        for index, frame in enumerate(frames, start=1):
            before = _metrics(url)
            result = _request(url, cfg["id"], [frame], 64, pair=False)
            if result.get("status") == "ok" and result.get("truncated"):
                before = _metrics(url)
                retry = _request(url, cfg["id"], [frame], 128, pair=False)
                retry["retried_from_64"] = True
                result = retry
            after = _metrics(url)
            result.update({
                "kind": "single",
                "frame": index,
                "prompt_ms": _delta(before, after, "llamacpp:prompt_seconds_total") * 1000,
                "prompt_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_total")),
                "prompt_cached_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_cached_total")),
                "predicted_tokens": int(_delta(before, after, "llamacpp:tokens_predicted_total")),
                "predicted_ms": _delta(before, after, "llamacpp:tokens_predicted_seconds_total") * 1000,
                "rss_mb": _rss_mb(process.pid),
            })
            cases.append(result)
            print(
                f"single {index:02d} status={result.get('status')} budget={result.get('budget')} "
                f"ttft={result.get('ttft_ms')} total={result.get('total_ms')} "
                f"prompt={result.get('prompt_ms')} gen={result.get('generation_ms')} "
                f"trunc={result.get('truncated')} | {result.get('caption')}",
                flush=True,
            )
        rss_single = _rss_mb(process.pid)
        pairs = [(5, 6), (6, 7), (7, 8), (9, 10)]
        for first, second in pairs:
            before = _metrics(url)
            result = _request(url, cfg["id"], [frames[first - 1], frames[second - 1]], 64, pair=True)
            if result.get("status") == "ok" and result.get("truncated"):
                before = _metrics(url)
                retry = _request(url, cfg["id"], [frames[first - 1], frames[second - 1]], 128, pair=True)
                retry["retried_from_64"] = True
                result = retry
            after = _metrics(url)
            result.update({
                "kind": "pair",
                "pair": f"{first}-{second}",
                "frames": [first, second],
                "prompt_ms": _delta(before, after, "llamacpp:prompt_seconds_total") * 1000,
                "prompt_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_total")),
                "prompt_cached_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_cached_total")),
                "predicted_tokens": int(_delta(before, after, "llamacpp:tokens_predicted_total")),
                "predicted_ms": _delta(before, after, "llamacpp:tokens_predicted_seconds_total") * 1000,
                "rss_mb": _rss_mb(process.pid),
            })
            cases.append(result)
            print(
                f"pair {first}-{second} status={result.get('status')} budget={result.get('budget')} "
                f"ttft={result.get('ttft_ms')} total={result.get('total_ms')} "
                f"prompt={result.get('prompt_ms')} gen={result.get('generation_ms')} "
                f"trunc={result.get('truncated')} | {result.get('caption')}",
                flush=True,
            )
        rss_pair = _rss_mb(process.pid)
        time.sleep(max(0.0, args.idle_seconds))
        rss_idle = _rss_mb(process.pid)
        singles = [item for item in cases if item["kind"] == "single" and item.get("status") == "ok"]
        pairs_only = [item for item in cases if item["kind"] == "pair" and item.get("status") == "ok"]
        output = {
            "model": cfg["id"],
            "cache": "disabled: --cache-ram 0 --no-cache-prompt --no-cache-idle-slots",
            "rss_mb": {"load": rss_load, "single": rss_single, "pair": rss_pair, "idle": rss_idle},
            "single_summary": {
                "runs": len([item for item in cases if item["kind"] == "single"]),
                "ok": len(singles),
                "retried_at_128": sum(1 for item in cases if item["kind"] == "single" and item.get("retried_from_64")),
                "ttft_ms": {"p50": statistics.median([item["ttft_ms"] for item in singles if item.get("ttft_ms")]) if singles else None},
                "total_ms": {"p50": statistics.median([item["total_ms"] for item in singles]) if singles else None},
                "prompt_ms": {"p50": statistics.median([item["prompt_ms"] for item in singles]) if singles else None},
                "generation_ms": {"p50": statistics.median([item["generation_ms"] for item in singles]) if singles else None},
            },
            "pair_summary": {
                "runs": len([item for item in cases if item["kind"] == "pair"]),
                "ok": len(pairs_only),
                "retried_at_128": sum(1 for item in cases if item["kind"] == "pair" and item.get("retried_from_64")),
                "ttft_ms": {"p50": statistics.median([item["ttft_ms"] for item in pairs_only if item.get("ttft_ms")]) if pairs_only else None},
                "total_ms": {"p50": statistics.median([item["total_ms"] for item in pairs_only]) if pairs_only else None},
                "prompt_ms": {"p50": statistics.median([item["prompt_ms"] for item in pairs_only]) if pairs_only else None},
                "generation_ms": {"p50": statistics.median([item["generation_ms"] for item in pairs_only]) if pairs_only else None},
            },
            "cases": cases,
        }
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in output.items() if k != "cases"}, ensure_ascii=False, indent=2), flush=True)
    finally:
        _stop_tree(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
