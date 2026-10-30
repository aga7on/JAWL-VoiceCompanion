"""Single-pass 50s A/V continuity probe against an already-running Omni server.

Uses ten timestamped stills plus the matching full audio track. This is an
exploratory multimodal baseline, not a CPU or live-capture acceptance test.
Decoded media is kept in a temporary directory; only the model reply and
scalar request metadata are written to the report.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIP = ROOT / "runtime/multimodal-realclips-20261024/real_sensory_5x10s.mp4"
DEFAULT_ENDPOINT = "http://127.0.0.1:8995/v1/chat/completions"
DEFAULT_MODEL = "qwen25-omni-sensory"


def request_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 5.0):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {} if data is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clip", type=Path, default=DEFAULT_CLIP)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=760)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/multimodal-realclips-20261024/qwen25-omni-full50-joint-20261024.json")
    args = parser.parse_args()
    clip = args.clip if args.clip.is_absolute() else ROOT / args.clip
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    if not clip.is_file():
        raise FileNotFoundError(clip)

    origin = args.endpoint.rsplit("/v1/", 1)[0]
    health = request_json(origin + "/health")
    props = request_json(origin + "/props")
    if health.get("status") != "ok" or props.get("model_alias") != args.model:
        raise RuntimeError("Existing endpoint health/model identity did not match; no inference sent")
    modalities = props.get("modalities") or {}
    if not (modalities.get("vision") and modalities.get("audio")):
        raise RuntimeError("Existing endpoint does not advertise both audio and vision")
    slots = request_json(origin + "/slots")
    slot_states = slots if isinstance(slots, list) else slots.get("value", [])
    if any(bool(slot.get("is_processing")) for slot in slot_states if isinstance(slot, dict)):
        raise RuntimeError("Existing endpoint has a busy slot; no inference sent")

    with tempfile.TemporaryDirectory(prefix="jawl-omni-full50-") as temp:
        temp_dir = Path(temp)
        wav_path = temp_dir / "audio.wav"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(wav_path),
        ], check=True, capture_output=True, timeout=90)
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir()
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
            "fps=1/5,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
            "-frames:v", "10", str(frames_dir / "%02d.jpg"),
        ], check=True, capture_output=True, timeout=90)
        frame_paths = sorted(frames_dir.glob("*.jpg"))
        if len(frame_paths) != 10:
            raise RuntimeError(f"Expected ten 5-second samples, got {len(frame_paths)}")

        content: list[dict] = [{
            "type": "text",
            "text": "Один синхронный видео- и аудиофрагмент длительностью 50 секунд. "
                    "Далее идут кадры по порядку; перед каждым кадром указан момент съёмки. "
                    "Последняя часть — аудио всего того же 50-секундного интервала. "
                    "Ответь по-русски и раздели: (1) видимые сцены и смены с примерными временами; "
                    "(2) слышимую речь, музыку и различимые звуковые события с примерными временами; "
                    "(3) только надёжно подтверждённую связь звука с изображением. "
                    "Не угадывай слова, жанр, инструменты или сюжет; если связь неясна, так и скажи.",
        }]
        frame_times = list(range(0, 50, 5))
        for frame_time, path in zip(frame_times, frame_paths, strict=True):
            content.append({"type": "text", "text": f"Кадр примерно на {frame_time}-й секунде:"})
            content.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")},
            })
        wav_bytes = wav_path.read_bytes()
        content.append({
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(wav_bytes).decode("ascii"), "format": "wav"},
        })
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": args.max_tokens,
            "temperature": 0.0,
            "cache_prompt": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(args.endpoint, data=body, headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=240) as response:
                result = json.loads(response.read().decode("utf-8"))
            error = None
        except urllib.error.HTTPError as exc:
            error = {"http_status": exc.code, "body_excerpt": exc.read(4096).decode("utf-8", "replace")}
            result = {}
        elapsed = time.perf_counter() - started

    choices = result.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    report = {
        "schema_version": 1,
        "case_id": "real_sensory_5x10s_full50_joint_av",
        "endpoint": args.endpoint,
        "model": args.model,
        "server_context_tokens": props.get("default_generation_settings", {}).get("n_ctx"),
        "server_modalities": modalities,
        "server_slots_idle_before_request": True,
        "cpu_only": False,
        "source": str(clip.relative_to(ROOT)) if clip.is_relative_to(ROOT) else clip.name,
        "source_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
        "duration_seconds": 50,
        "video_samples_seconds": frame_times,
        "video_sample_size": "640x360 letterboxed",
        "audio_sample": "same 50 seconds, mono 16 kHz PCM16 WAV",
        "raw_frames_or_pcm_persisted": False,
        "cache_prompt": False,
        "max_tokens": payload["max_tokens"],
        "latency_seconds": round(elapsed, 3),
        "usage": result.get("usage"),
        "finish_reason": choice.get("finish_reason"),
        "response": message.get("content", ""),
        "error": error or result.get("error"),
        "limitations": [
            "Single exploratory call to Qwen2.5-Omni on its existing non-CPU endpoint; not the modular production lanes.",
            "One still every five seconds cannot ground brief actions or exact scene boundaries.",
            "The model sees the full audio and sparse timestamped stills, not a continuous video stream.",
            "No human-scored audio transcript, music-style labels, or scene event ledger is supplied by this run.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(output_path),
        "latency_seconds": report["latency_seconds"],
        "usage": report["usage"],
        "finish_reason": report["finish_reason"],
        "error": report["error"],
        "response": report["response"],
    }, ensure_ascii=False))
    return 0 if report["error"] is None and report["response"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
