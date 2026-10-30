"""Live sensory run: two displays + system audio -> full report.

Captures both displays and ~N seconds of system audio (user is watching
open YouTube), then produces:
  1. EG2 zero-decoder tags per display and audio;
  2. Detailed visual description via the local VLM (Bonsai on :8090);
  3. Exact Russian transcript via crispasr/GigaAM;
  4. Sound/music description from the spectrogram via the VLM;
  5. Final fused answer from the brain model (Russian).

Everything is saved under runtime/live-sensory-run/. No raw media is kept
beyond the run directory.
"""
from __future__ import annotations

import base64
import io
import json
import struct
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402
from jawl_voicecompanion.system_audio import SystemAudioLoopback  # noqa: E402
from jawl_voicecompanion.eg2_sensory import (  # noqa: E402
    DEFAULT_EG2_ONNX_ROOT,
    EmbeddingGemmaSensoryCortex,
)

OUT = ROOT / "runtime" / "live-sensory-run"
OUT.mkdir(parents=True, exist_ok=True)

MODEL_URL = "http://127.0.0.1:8090/v1/chat/completions"
CRISPASR = r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe"
GIGAAM_MODEL = str(ROOT / "runtime" / "models" / "asr" / "gigaam-v3-e2e-rnnt-q8_0.gguf")
AUDIO_SECONDS = 6.0


def llm(messages, *, max_tokens=600, temperature=0.4) -> str:
    body = {
        "model": "bonsai-2-27b",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        MODEL_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    msg = data["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def capture_displays():
    adapter = ScreenCaptureAdapter(enabled=True)
    captures = adapter.capture_displays(max_displays=2)
    images = []
    for index, capture in enumerate(captures):
        if capture.get("status") == "verified" and isinstance(capture.get("image"), dict):
            encoded = capture["image"]["data_base64"]
            images.append((index, base64.b64decode(encoded), encoded))
            (OUT / f"display{index + 1}.jpg").write_bytes(base64.b64decode(encoded))
    return images


def capture_system_audio(seconds: float):
    pcm_chunks: list[bytes] = []
    rate_box = [0]
    channel_box = [0]

    def consumer(pcm, sr, ch, session_id):
        pcm_chunks.append(bytes(pcm))
        rate_box[0] = sr
        channel_box[0] = ch

    loopback = SystemAudioLoopback(consumer)
    state = loopback.start()
    print(f"[audio] device={state.get('device')} sr={state.get('sample_rate')} ch={state.get('channels')}")
    time.sleep(seconds)
    loopback.stop(timeout=4)
    if not pcm_chunks:
        return None
    pcm = b"".join(pcm_chunks)
    sr = rate_box[0] or 48000
    ch = channel_box[0] or 2
    if ch > 1:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        samples = samples.reshape(-1, ch).mean(axis=1)
        pcm = samples.astype(np.int16).tobytes()
        ch = 1
    # 16 kHz mono for ASR
    if sr != 16000:
        import numpy as _np
        samples = _np.frombuffer(pcm, dtype=_np.int16).astype(_np.float32) / 32768.0
        count = int(len(samples) * 16000 / sr)
        indices = _np.linspace(0, len(samples) - 1, count).astype(int)
        resampled = _np.interp(indices, _np.arange(len(samples)), samples)
        pcm = (resampled * 32767).astype(_np.int16).tobytes()
        sr = 16000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    wav_bytes = buf.getvalue()
    (OUT / "system_audio.wav").write_bytes(wav_bytes)
    return wav_bytes


def gigaam_transcribe(wav_bytes: bytes) -> str:
    tmp_in = OUT / "asr_in.wav"
    tmp_out = OUT / "asr_out"
    tmp_in.write_bytes(wav_bytes)
    for stale in OUT.glob("asr_out*"):
        stale.unlink()
    command = [CRISPASR, "-m", GIGAAM_MODEL, "-oj", "-of", str(tmp_out), str(tmp_in)]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120, cwd=str(OUT))
    if proc.returncode != 0:
        return f"[crispasr error: {proc.stderr.strip()[:200]}]"
    for candidate in (OUT / "asr_out.json", OUT / "asr_out.wav.json"):
        if candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            results = payload.get("transcription") or payload.get("result") or payload
            if isinstance(results, list):
                texts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in results]
                return " ".join(t for t in texts if t).strip()
            if isinstance(results, dict):
                return str(results.get("text") or results.get("transcription") or "").strip()
    return "[crispasr produced no output]"


def spectrogram_png(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sr = w.getframerate()
        pcm = w.readframes(w.getnframes())
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n_fft, hop = 1024, 256
    window = np.hanning(n_fft)
    frames = 1 + max(0, (len(samples) - n_fft) // hop)
    S = np.zeros((n_fft // 2 + 1, max(1, frames)))
    for i in range(frames):
        seg = samples[i * hop : i * hop + n_fft] * window
        S[:, i] = np.abs(np.fft.rfft(seg, n=n_fft)) ** 2
    S_db = 10 * np.log10(S + 1e-10)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.imshow(
        S_db,
        aspect="auto",
        origin="lower",
        cmap="magma",
        extent=[0, len(samples) / sr, 0, sr / 2],
    )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_title("System audio spectrogram")
    fig.tight_layout()
    path = OUT / "spectrogram.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.read_bytes()


def main() -> None:
    report: dict[str, object] = {}

    print("[1/6] capturing displays...")
    displays = capture_displays()
    report["displays_captured"] = len(displays)
    print(f"      {len(displays)} displays captured")

    print(f"[2/6] capturing {AUDIO_SECONDS}s of system audio...")
    audio_wav = capture_system_audio(AUDIO_SECONDS)
    report["audio_captured"] = audio_wav is not None
    print(f"      audio bytes: {len(audio_wav) if audio_wav else 0}")

    print("[3/6] EG2 zero-decoder tags...")
    cortex = EmbeddingGemmaSensoryCortex(DEFAULT_EG2_ONNX_ROOT)
    images = [data for _, data, _ in displays]
    eg2_desc = cortex.describe_displays(images, audio_wav_bytes=audio_wav)
    (OUT / "eg2_desc.txt").write_text(eg2_desc, encoding="utf-8")
    report["eg2"] = eg2_desc
    print(f"      {eg2_desc}")

    print("[4/6] detailed visual description (VLM)...")
    visual_parts = []
    for index, _, encoded in displays:
        desc = llm(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Опиши подробно и конкретно, что происходит на этом скриншоте: "
                                "какой сайт/плеер, что за видео, видимый текст, обстановка. "
                                "По-русски, 3-5 предложений."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded}},
                    ],
                }
            ]
        )
        visual_parts.append(f"Дисплей {index + 1}: {desc}")
    visual = "\n\n".join(visual_parts)
    (OUT / "visual_desc.txt").write_text(visual, encoding="utf-8")
    report["visual"] = visual
    print(f"      saved {len(visual)} chars")

    print("[5/6] exact transcript (GigaAM) + sound description...")
    transcript = gigaam_transcribe(audio_wav) if audio_wav else "[no audio]"
    (OUT / "transcript.txt").write_text(transcript, encoding="utf-8")
    report["transcript"] = transcript
    print(f"      transcript: {transcript[:200]}")

    sound_desc = ""
    if audio_wav:
        spec_b64 = base64.b64encode(spectrogram_png(audio_wav)).decode()
        sound_desc = llm(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Это спектрограмма системного аудио (несколько секунд) с компьютера, "
                                "где играет видео с YouTube. Опиши по-русски детально: какие звуки, "
                                "речь или музыка, темп, настроение. 3-5 предложений."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + spec_b64}},
                    ],
                }
            ]
        )
        (OUT / "sound_desc.txt").write_text(sound_desc, encoding="utf-8")
        report["sound"] = sound_desc
        print(f"      sound desc: {len(sound_desc)} chars")

    print("[6/6] final fused answer (brain)...")
    context = (
        f"EG2-сенсоры: {eg2_desc}\n\n"
        f"Визуальное описание:\n{visual}\n\n"
        f"Точная транскрипция звука (ASR): {transcript}\n\n"
        f"Описание звука: {sound_desc or 'нет'}"
    )
    answer = llm(
        [
            {
                "role": "system",
                "content": (
                    "Ты — JAWL, живой компаньон, смотришь и слушаешь вместе с владельцем. "
                    "Ответь по-русски, 3-6 предложений: перескажи происходящее на экране и в звуке, "
                    "включая услышанную речь, и отреагируй как друг. Не выдумывай деталей."
                ),
            },
            {"role": "user", "content": context},
        ],
        max_tokens=700,
    )
    (OUT / "final_answer.txt").write_text(answer, encoding="utf-8")
    report["answer"] = answer

    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== FINAL ANSWER ===")
    print(answer)


if __name__ == "__main__":
    main()
