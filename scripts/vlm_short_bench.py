"""Short-caption benchmark: unique sequential frames, full vs crop, 32/64 tokens.

No OCR or audio fields. Prompt cache and RAM prompt cache are disabled so that
every image is processed again; repeated images are a separate group.
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

SHORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["caption", "events", "uncertainty"],
    "properties": {
        "caption": {"type": "string", "maxLength": 240},
        "events": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 120},
        },
        "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

SYSTEM = (
    "You are a concise vision describer. Return only valid JSON matching the "
    "schema. Do not transcribe text (no OCR). Do not mention audio."
)
USER = (
    "Caption the image in one short sentence (maximum 20 words), list up to 3 "
    "visible events or details, and give uncertainty 0..1. Do not quote or "
    "transcribe on-screen text. Return JSON only."
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
        response = requests.get(url + "/metrics", timeout=5)
        for line in response.text.splitlines():
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


def _start_server(cfg: dict[str, Any], runtime: dict[str, Any], log_dir: Path) -> tuple[subprocess.Popen, str]:
    model = Path(cfg["file"])
    mmproj = Path(cfg["mmproj"])
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / f"{cfg['id']}-short.out.log"
    err_path = log_dir / f"{cfg['id']}-short.err.log"
    command = [
        runtime["llama_server"],
        "-m", str(model),
        "--mmproj", str(mmproj),
        "--host", "127.0.0.1",
        "--port", str(cfg["port"]),
        "-c", str(runtime.get("context", 4096)),
        "-np", "1",
        "-t", str(runtime.get("threads", 6)),
        "-tb", str(runtime.get("threads_batch", 6)),
        "--jinja",
        "--reasoning", "off",
        "-ngl", "0",
        "--no-mmproj-offload",
        "--metrics",
        "--cache-ram", "0",
        "--no-cache-prompt",
        "--no-cache-idle-slots",
    ]
    out_handle = out_path.open("ab")
    err_handle = err_path.open("ab")
    process = subprocess.Popen(
        command,
        cwd=str(Path(runtime["llama_server"]).parent),
        stdout=out_handle,
        stderr=err_handle,
    )
    url = f"http://127.0.0.1:{cfg['port']}"
    deadline = time.time() + 240
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            if requests.get(url + "/health", timeout=2).status_code == 200:
                return process, url
        except requests.RequestException:
            pass
        time.sleep(1)
    tail = err_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    _stop_tree(process.pid)
    raise RuntimeError(f"server failed: {tail}")


def _request(url: str, model: str, image: Path, budget: int) -> dict[str, Any]:
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                ],
            },
        ],
        "max_tokens": budget,
        "temperature": 0.0,
        "top_p": 0.9,
        "stream": True,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "short_caption", "schema": SHORT_SCHEMA},
        },
    }
    started = time.perf_counter()
    ttft = None
    text = ""
    try:
        response = requests.post(url + "/chat/completions", json=payload, stream=True, timeout=180)
        if response.status_code >= 400:
            return {
                "status": "http_error",
                "error": response.text[:500],
                "ttft_ms": None,
                "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
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
            delta = (event.get("choices") or [{}])[0].get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                if ttft is None:
                    ttft = round((time.perf_counter() - started) * 1000.0, 1)
                text += piece
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "request_error",
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "ttft_ms": None,
            "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }
    total = round((time.perf_counter() - started) * 1000.0, 1)
    try:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.strip("`").replace("json\n", "", 1)
        start, end = clean.find("{"), clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object")
        payload_out = json.loads(clean[start : end + 1])
        valid = (
            isinstance(payload_out.get("caption"), str)
            and payload_out["caption"].strip() != ""
            and isinstance(payload_out.get("events"), list)
            and isinstance(payload_out.get("uncertainty"), (int, float))
            and not isinstance(payload_out.get("uncertainty"), bool)
            and 0 <= float(payload_out["uncertainty"]) <= 1
        )
        return {
            "status": "ok" if valid else "schema_invalid",
            "payload": payload_out,
            "text": text[:2000],
            "ttft_ms": ttft,
            "total_ms": total,
            "generation_ms": round(total - (ttft or total), 1),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "invalid_json",
            "error": f"{type(exc).__name__}: {exc}",
            "text": text[:2000],
            "ttft_ms": ttft,
            "total_ms": total,
            "generation_ms": round(total - (ttft or total), 1),
        }


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for group in ("unique", "repeat"):
        selected = [item for item in cases if item["group"] == group]
        for budget in (32, 64):
            subset = [item for item in selected if item["max_tokens"] == budget]
            if not subset:
                continue
            ok = [item for item in subset if item.get("status") == "ok"]
            ttft = [float(item["ttft_ms"]) for item in ok if item.get("ttft_ms") is not None]
            total = [float(item["total_ms"]) for item in ok if item.get("total_ms") is not None]
            prompt_ms = [float(item["prompt_ms"]) for item in ok if item.get("prompt_ms") is not None]
            gen_ms = [float(item["generation_ms"]) for item in ok if item.get("generation_ms") is not None]
            out[f"{group}_{budget}"] = {
                "runs": len(subset),
                "ok": len(ok),
                "invalid_json": sum(1 for item in subset if item.get("status") == "invalid_json"),
                "schema_invalid": sum(1 for item in subset if item.get("status") == "schema_invalid"),
                "ttft_ms": {"p50": statistics.median(ttft) if ttft else None, "p95": _percentile(ttft, 0.95)},
                "total_ms": {"p50": statistics.median(total) if total else None, "p95": _percentile(total, 0.95)},
                "prompt_ms": {"p50": statistics.median(prompt_ms) if prompt_ms else None, "p95": _percentile(prompt_ms, 0.95)},
                "generation_ms": {"p50": statistics.median(gen_ms) if gen_ms else None, "p95": _percentile(gen_ms, 0.95)},
                "cached_prompt_tokens": sum(int(item.get("prompt_cached_tokens", 0)) for item in subset),
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/vlm-cpu-bench.json"))
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--frames", default=str(ROOT / "runtime/vlm-cpu-bench/sequence"))
    parser.add_argument("--out-dir", default=str(ROOT / "runtime/vlm-cpu-bench/short"))
    parser.add_argument("--idle-seconds", type=float, default=20.0)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    models = [
        model for model in config["models"]
        if model.get("run") and model["id"] in (args.model or ["lfm2.5-vl-450m", "qwen3.5-0.8b"])
    ]
    frames_dir = Path(args.frames)
    full = sorted(frames_dir.glob("screen-*.jpg"))
    crop = sorted(frames_dir.glob("crop-*.jpg"))
    if not full or len(full) != len(crop):
        raise SystemExit("missing full/crop sequence")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_models = []
    for cfg in models:
        print(f"=== {cfg['id']} ===", flush=True)
        process, url = _start_server(cfg, config["runtime"], out_dir / "logs")
        try:
            pid = process.pid
            rss_load = _rss_mb(pid)
            cases: list[dict[str, Any]] = []
            # Unique sequence: alternating full/crop and 32/64 budgets.
            for index, (full_path, crop_path) in enumerate(zip(full, crop), start=1):
                for kind, path in (("full", full_path), ("crop", crop_path)):
                    for budget in (32, 64):
                        before = _metrics(url)
                        result = _request(url, cfg["id"], path, budget)
                        after = _metrics(url)
                        result.update({
                            "group": "unique",
                            "frame": index,
                            "kind": kind,
                            "max_tokens": budget,
                            "prompt_ms": _delta(before, after, "llamacpp:prompt_seconds_total") * 1000,
                            "prompt_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_total")),
                            "prompt_cached_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_cached_total")),
                            "predicted_tokens": int(_delta(before, after, "llamacpp:tokens_predicted_total")),
                            "predicted_ms": _delta(before, after, "llamacpp:tokens_predicted_seconds_total") * 1000,
                            "rss_mb": _rss_mb(pid),
                        })
                        cases.append(result)
                        print(
                            f"unique frame={index:02d} {kind} mt={budget} {result.get('status')} "
                            f"ttft={result.get('ttft_ms')} total={result.get('total_ms')} "
                            f"prompt={result.get('prompt_ms')} gen={result.get('generation_ms')} "
                            f"cached={result.get('prompt_cached_tokens')}",
                            flush=True,
                        )
            rss_unique = _rss_mb(pid)
            # Repeat the same full frame 3 times at 64 tokens.
            for repeat in range(3):
                before = _metrics(url)
                result = _request(url, cfg["id"], full[2], 64)
                after = _metrics(url)
                result.update({
                    "group": "repeat",
                    "frame": 3,
                    "kind": "full",
                    "max_tokens": 64,
                    "repeat": repeat,
                    "prompt_ms": _delta(before, after, "llamacpp:prompt_seconds_total") * 1000,
                    "prompt_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_total")),
                    "prompt_cached_tokens": int(_delta(before, after, "llamacpp:prompt_tokens_cached_total")),
                    "predicted_tokens": int(_delta(before, after, "llamacpp:tokens_predicted_total")),
                    "predicted_ms": _delta(before, after, "llamacpp:tokens_predicted_seconds_total") * 1000,
                    "rss_mb": _rss_mb(pid),
                })
                cases.append(result)
                print(
                    f"repeat {repeat} mt=64 {result.get('status')} ttft={result.get('ttft_ms')} "
                    f"total={result.get('total_ms')} prompt={result.get('prompt_ms')} "
                    f"gen={result.get('generation_ms')} cached={result.get('prompt_cached_tokens')}",
                    flush=True,
                )
            rss_repeat = _rss_mb(pid)
            time.sleep(max(0.0, args.idle_seconds))
            rss_idle = _rss_mb(pid)
            result = {
                "model": cfg["id"],
                "repo": cfg.get("repo"),
                "revision": cfg.get("revision"),
                "cache": "disabled: --cache-ram 0 --no-cache-prompt --no-cache-idle-slots",
                "frames": [str(path) for path in full],
                "crops": [str(path) for path in crop],
                "rss_mb": {
                    "load": rss_load,
                    "unique": rss_unique,
                    "repeat": rss_repeat,
                    "idle": rss_idle,
                },
                "summary": _summary(cases),
                "cases": cases,
            }
            path = out_dir / f"{cfg['id']}.json"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            all_models.append({k: v for k, v in result.items() if k != "cases"})
            print(json.dumps(result["summary"], ensure_ascii=False, indent=2), flush=True)
            print(json.dumps(result["rss_mb"], ensure_ascii=False), flush=True)
        finally:
            _stop_tree(process.pid)
    (out_dir / "summary.json").write_text(json.dumps(all_models, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {out_dir / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
