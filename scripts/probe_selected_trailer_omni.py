"""Compare separate and joint Qwen2.5-Omni observations on a Russian trailer.

Uses the already-running local endpoint without changing server configuration.
Samples video at 1 fps/640x360 and sends the matching 10s audio as WAV.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIP = ROOT / "runtime/instances/realclip-sensory-20261024/russian-trailer.mp4"
ENDPOINT = "http://127.0.0.1:8995/v1/chat/completions"
MODEL = "qwen25-omni-sensory"


def _post(payload: dict, timeout: float) -> tuple[dict, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result, (time.perf_counter() - started)


def _text(content: list[dict], prompt: str) -> list[dict]:
    return [{"type": "text", "text": prompt}, *content]


def _request(content: list[dict], prompt: str, limit: int) -> dict:
    result, elapsed = _post({
        "model": MODEL,
        "messages": [{"role": "user", "content": _text(content, prompt)}],
        "max_tokens": limit,
        "temperature": 0.0,
        "cache_prompt": False,
    }, timeout=120)
    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "latency_seconds": round(elapsed, 3),
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage"),
        "response": message.get("content", ""),
        "error": result.get("error"),
    }


def main() -> int:
    global ENDPOINT, MODEL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--video-only", action="store_true", help="skip audio and joint calls; use for a visual-only server")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/audio-path-replay/out/project-hail-mary-qwen25-omni-20261024.json")
    args = parser.parse_args()
    ENDPOINT, MODEL = args.endpoint, args.model
    if not CLIP.is_file():
        raise FileNotFoundError(CLIP)

    with tempfile.TemporaryDirectory(prefix="jawl-omni-trailer-") as temp:
        temp_dir = Path(temp)
        wav = temp_dir / "audio.wav"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", str(CLIP), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
        ], check=True, capture_output=True, timeout=60)
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir()
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", str(CLIP), "-vf",
            "fps=1,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
            "-frames:v", "10", str(frames_dir / "%02d.jpg"),
        ], check=True, capture_output=True, timeout=60)
        frames = sorted(frames_dir.glob("*.jpg"))
        if not 8 <= len(frames) <= 10:
            raise RuntimeError(f"expected 8-10 sampled video frames, got {len(frames)}")
        image_parts = [{
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")},
        } for path in frames]
        wav_bytes = wav.read_bytes()
        audio_part = {
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(wav_bytes).decode("ascii"), "format": "wav"},
        }

        video = _request(
            image_parts,
            "Опиши по-русски последовательность видимых кадров. Только наблюдаемые визуальные факты: сцены, объекты, изменения. Не угадывай сюжет и не описывай звук.",
            320,
        )
        audio = joint = joint_audio_first = None
        if not args.video_only:
            audio = _request(
                [audio_part],
                "Опиши по-русски только слышимое в этом фрагменте: речь (кратко передай смысл без дословных длинных цитат), наличие музыки и различимые звуковые события. Не угадывай жанр или настроение без явных признаков.",
                240,
            )
            joint_prompt = "Это один синхронный 10-секундный фрагмент. Ответь ровно тремя короткими строками: Видно (до 3 реальных смен), Слышно (речь/музыка и смысл), Связь (один подтверждённый A/V факт или «неясна»). Не повторяй одинаковые соседние кадры, не переноси факт между модальностями. Всего до 45 слов."
            joint = _request([*image_parts, audio_part], joint_prompt, 180)
            joint_audio_first = _request([audio_part, *image_parts], joint_prompt, 180)

    items = {
        "video_only": video,
        "audio_only": audio,
        "joint_av_video_first": joint,
        "joint_av_audio_first": joint_audio_first,
    }
    report = {
        "schema_version": 1,
        "case_id": "project_hail_mary_russian_trailer_30_40",
        "endpoint": ENDPOINT,
        "model": MODEL,
        "local_clip_sha256": hashlib.sha256(CLIP.read_bytes()).hexdigest(),
        "scope": "same 10s interval, 1fps 640x360 video-only, audio-only, and joint A/V requests; cache_prompt=false",
        "video_frames": len(frames),
        "video_sampling": "1 fps, max 10 frames, 640x360 letterbox",
        "audio_format": "mono 16kHz PCM16 WAV, extracted to temporary storage",
        "raw_audio_persisted": False,
        "items": {key: value for key, value in items.items() if value is not None},
        "limitations": [
            "Direct model endpoint only; no companion capture/fusion/brain-turn acceptance.",
            "Sparse 1fps frames can miss brief actions and transitions.",
            "Responses must be scored against the visual contact sheet and the separate transcript/soundscape probe.",
            "One trailer excerpt cannot establish general multimodal accuracy or always-on cost.",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(output),
        "frames": len(frames),
        "latencies_seconds": {key: value.get("latency_seconds") for key, value in report["items"].items()},
        "finish_reasons": {key: value.get("finish_reason") for key, value in report["items"].items()},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
