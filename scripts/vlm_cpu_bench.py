"""Run the same 13 Gemma cases against CPU vision-language models.

The 13 cases and the observation schema are shared with the Gemma probe.  For
vision-only models the six audio-only cases are deliberately sent without an
image: they are negative controls for "no visual evidence" and must not invent
a scene.  Combined cases send the first display frame only.
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
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.gemma_sensory import (  # noqa: E402
    OBSERVATION_SCHEMA,
    _extract_json,
    normalize_observation,
)

SYSTEM_IMAGE = (
    "You are a concise vision describer for a desktop companion. "
    "Describe only visible evidence. Return only valid JSON matching the schema. "
    "Do not describe audio. Set every audio field to an empty string, an empty "
    "list, or 'unknown'. Do not invent objects or text."
)
USER_IMAGE = (
    "Describe the visible scene specifically: the type of content (game, video, "
    "website, app, document, people), the main objects or changes, and any "
    "readable text. Do not guess unseen details. Return JSON only."
)
SYSTEM_NO_IMAGE = (
    "No image is attached. Do not invent a scene. Return only valid JSON matching "
    "the schema. Set scene to 'unknown', changes to an empty list, uncertainty to "
    "at least 0.8, and every audio field to an empty value or 'unknown'."
)
USER_NO_IMAGE = (
    "There is no image in this request. Report that the visual scene is unknown "
    "without inventing objects, people, text, or audio. Return JSON only."
)

EXTRA_ARGS = ["--jinja", "--reasoning", "off", "-ngl", "0", "--no-mmproj-offload"]


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 1)


def _case_image(name: str, images: list[Path]) -> Path | None:
    if name.startswith("image_"):
        index = int(name.rsplit("_", 1)[1]) - 1
        return images[index] if 0 <= index < len(images) else None
    if name.startswith("combined_"):
        return images[0] if images else None
    return None


def _cases(images: list[Path]) -> list[str]:
    names = [f"image_{i + 1}" for i in range(len(images))]
    names += ["ru_speech", "en_speech", "music", "noise", "silence", "speech_music"]
    names += [
        "combined_ru_speech",
        "combined_music",
        "combined_speech_music",
        "combined_noise",
        "combined_silence",
    ]
    return names


def _payload(model: str, image: Path | None, max_tokens: int, with_schema: bool) -> dict[str, Any]:
    system_prompt = SYSTEM_IMAGE if image is not None else SYSTEM_NO_IMAGE
    user_prompt = USER_IMAGE if image is not None else USER_NO_IMAGE
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    if image is not None:
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
        })
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "top_p": 0.9,
        "stream": True,
    }
    if with_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "jawl_sensory_observation", "schema": OBSERVATION_SCHEMA},
        }
    return payload


def _request(model: str, url: str, image: Path | None, max_tokens: int) -> dict[str, Any]:
    started = time.perf_counter()
    ttft_ms = None
    text = ""
    reasoning = ""
    status_code = None
    error = None
    schema_sent = True
    try:
        response = requests.post(
            url + "/chat/completions",
            json=_payload(model, image, max_tokens, True),
            stream=True,
            timeout=180,
        )
        status_code = response.status_code
        if status_code >= 400:
            body = response.text[:400]
            if status_code in (400, 422):
                response.close()
                schema_sent = False
                response = requests.post(
                    url + "/chat/completions",
                    json=_payload(model, image, max_tokens, False),
                    stream=True,
                    timeout=180,
                )
                status_code = response.status_code
                if status_code >= 400:
                    return {
                        "status": "http_error",
                        "http_status": status_code,
                        "error": body,
                        "ttft_ms": None,
                        "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
                        "schema_sent": True,
                    }
            else:
                return {
                    "status": "http_error",
                    "http_status": status_code,
                    "error": body,
                    "ttft_ms": None,
                    "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
                    "schema_sent": schema_sent,
                }
        for raw_line in response.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
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
                if ttft_ms is None:
                    ttft_ms = round((time.perf_counter() - started) * 1000.0, 1)
                text += piece
            thought = delta.get("reasoning_content") or ""
            if thought:
                reasoning += thought
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "request_error",
            "error": f"{type(exc).__name__}: {exc}",
            "ttft_ms": None,
            "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "schema_sent": schema_sent,
        }
    total_ms = round((time.perf_counter() - started) * 1000.0, 1)
    combined = text or reasoning
    try:
        payload = _extract_json(combined)
        status = "ok"
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "invalid_json",
            "error": f"{type(exc).__name__}: {exc}",
            "text": combined[:4000],
            "reasoning": reasoning[:1000],
            "ttft_ms": ttft_ms,
            "total_ms": total_ms,
            "schema_sent": schema_sent,
            "used_reasoning": not bool(text) and bool(reasoning),
        }
    return {
        "status": status,
        "payload": payload,
        "text": combined[:4000],
        "reasoning": reasoning[:1000],
        "ttft_ms": ttft_ms,
        "total_ms": total_ms,
        "schema_sent": schema_sent,
        "used_reasoning": not bool(text) and bool(reasoning),
    }


def _rss_mb(pid: int) -> float:
    try:
        process = psutil.Process(pid)
        processes = [process, *process.children(recursive=True)]
        total = 0
        for item in processes:
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
        for child in reversed(children):
            try:
                if child.is_running():
                    child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def run_model(cfg: dict[str, Any], runtime: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    model_id = cfg["id"]
    model_path = Path(cfg["file"])
    mmproj = Path(cfg["mmproj"])
    missing = [str(path) for path in (model_path, mmproj) if not path.is_file()]
    if missing:
        return {"status": "missing_weights", "model": model_id, "missing": missing}
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{model_id}.out.log"
    stderr_path = log_dir / f"{model_id}.err.log"
    command = [
        runtime["llama_server"],
        "-m", str(model_path),
        "--mmproj", str(mmproj),
        "--host", "127.0.0.1",
        "--port", str(cfg["port"]),
        "-c", str(runtime.get("context", 4096)),
        "-np", str(runtime.get("parallel", 1)),
        "-t", str(runtime.get("threads", 6)),
        "-tb", str(runtime.get("threads_batch", 6)),
        *EXTRA_ARGS,
    ]
    with stdout_path.open("wb") as out_handle, stderr_path.open("wb") as err_handle:
        process = subprocess.Popen(
            command,
            cwd=str(Path(runtime["llama_server"]).parent),
            stdout=out_handle,
            stderr=err_handle,
        )
    url = f"http://127.0.0.1:{cfg['port']}"
    deadline = time.time() + float(runtime.get("health_timeout_s", 240))
    health = None
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            response = requests.get(url + "/health", timeout=2)
            if response.status_code == 200:
                health = response.json()
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    if health is None:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        _stop_tree(process.pid)
        return {
            "status": "server_error",
            "model": model_id,
            "returncode": process.returncode,
            "stderr_tail": tail,
        }
    images = [
        ROOT / "runtime/live-sensory-run/display1.jpg",
        ROOT / "runtime/live-sensory-run/display2.jpg",
    ]
    images = [path for path in images if path.is_file()]
    cases = _cases(images)
    results: list[dict[str, Any]] = []
    rss_after_load = _rss_mb(process.pid)
    for max_tokens in runtime.get("max_tokens", [160]):
        for case in cases:
            image = _case_image(case, images)
            result = _request(model_id, url, image, int(max_tokens))
            result["case"] = case
            result["max_tokens"] = int(max_tokens)
            result["source"] = "screen" if image else "no_image"
            result["rss_mb"] = _rss_mb(process.pid)
            if result.get("status") == "ok":
                now = time.time()
                frame = normalize_observation(
                    result.get("payload"),
                    source=result["source"],
                    observed_interval=[now, now],
                    observed_at=now,
                    processed_at=time.time(),
                    model=model_id,
                    quant="q4",
                    schema_valid=None,
                )
                result["schema_valid"] = frame["schema_valid"]
                result["scene"] = frame["scene"]
                result["uncertainty"] = frame["uncertainty"]
                result["audio_speech"] = frame["audio"]["speech"]
            else:
                result["schema_valid"] = False
            results.append(result)
            print(
                f"{model_id} mt={max_tokens} {case}: {result.get('status')} "
                f"ttft={result.get('ttft_ms')} total={result.get('total_ms')} "
                f"rss={result.get('rss_mb')}",
                flush=True,
            )
    rss_after = _rss_mb(process.pid)
    _stop_tree(process.pid)
    return {
        "status": "ok",
        "model": model_id,
        "repo": cfg.get("repo"),
        "revision": cfg.get("revision"),
        "health": health,
        "rss_after_load_mb": rss_after_load,
        "rss_after_runs_mb": rss_after,
        "cases": results,
    }


def summarize(model_result: dict[str, Any]) -> dict[str, Any]:
    if model_result.get("status") != "ok":
        return model_result
    cases = model_result["cases"]
    out: dict[str, Any] = {
        "model": model_result["model"],
        "rss_after_load_mb": model_result["rss_after_load_mb"],
        "rss_after_runs_mb": model_result["rss_after_runs_mb"],
        "by_budget": {},
    }
    for budget in sorted({item["max_tokens"] for item in cases}):
        selected = [item for item in cases if item["max_tokens"] == budget]
        ok = [item for item in selected if item.get("status") == "ok"]
        image_cases = [item for item in selected if item.get("source") == "screen"]
        no_image = [item for item in selected if item.get("source") == "no_image"]
        ttft = [float(item["ttft_ms"]) for item in ok if item.get("ttft_ms") is not None]
        total = [float(item["total_ms"]) for item in ok if item.get("total_ms") is not None]
        out["by_budget"][str(budget)] = {
            "runs": len(selected),
            "ok": len(ok),
            "invalid_json": sum(1 for item in selected if item.get("status") == "invalid_json"),
            "http_errors": sum(1 for item in selected if item.get("status") == "http_error"),
            "request_errors": sum(1 for item in selected if item.get("status") == "request_error"),
            "schema_valid": sum(1 for item in ok if item.get("schema_valid")),
            "image_ok": sum(1 for item in image_cases if item.get("status") == "ok"),
            "image_total": len(image_cases),
            "no_image_honest": sum(
                1 for item in no_image
                if item.get("status") == "ok"
                and "unknown" in str(item.get("scene", "")).lower()
            ),
            "no_image_total": len(no_image),
            "ttft_ms": {
                "p50": statistics.median(ttft) if ttft else None,
                "p95": _percentile(ttft, 0.95),
            },
            "total_ms": {
                "p50": statistics.median(total) if total else None,
                "p95": _percentile(total, 0.95),
            },
            "schema_sent": sum(1 for item in selected if item.get("schema_sent")),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/vlm-cpu-bench.json"))
    parser.add_argument("--out-dir", default=str(ROOT / "runtime/vlm-cpu-bench/out"))
    parser.add_argument("--model", action="append", default=[])
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = [
        model for model in config["models"]
        if model.get("run") and (not args.model or model["id"] in args.model)
    ]
    all_results = []
    for model in selected:
        print(f"=== {model['id']} ===", flush=True)
        result = run_model(model, config["runtime"], out_dir)
        summary = summarize(result)
        all_results.append(summary)
        full_path = out_dir / f"{model['id']}.full.json"
        full_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path = out_dir / f"{model['id']}.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2)[:6000], flush=True)
    aggregate = out_dir / "summary.json"
    aggregate.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {aggregate}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
