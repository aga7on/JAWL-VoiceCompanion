"""Streaming sensory worker prototype: desktop screen + system audio.

Produces typed sensory events as NDJSON lines. Fast extractors run
constantly on CPU; CLAP/whisper/VLM are consumed over HTTP from their
existing sidecar endpoints so this process stays light. This is a
capability worker: it never writes canonical memory or touches JAWL
policy; consumers own integration.

Run with the vision venv python:
  python scripts/sensory_worker.py --duration 900 --out runtime/sensory.ndjson
"""

from __future__ import annotations

import argparse
import collections
import ctypes
import json
import math
import queue
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SR = 16000


def now() -> float:
    return round(time.time(), 3)


def emit(out_stream, event: dict) -> None:
    out_stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    out_stream.flush()


def active_window_title() -> str:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value if length else ""


def image_phash_small(gray: np.ndarray, size: int = 8) -> int:
    import numpy as np
    step_h = max(1, gray.shape[0] // size)
    step_w = max(1, gray.shape[1] // size)
    block = gray[: size * step_h, : size * step_w]
    blocks = block.reshape(size, step_h, size, step_w).mean(axis=(1, 3))
    flat = blocks.flatten()
    median = np.median(flat)
    bits = flat > median
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return int(value)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class AudioRing:
    def __init__(self, seconds: int = 120) -> None:
        self.capacity = seconds * SR
        self.buf = collections.deque(maxlen=self.capacity)

    def extend(self, pcm16: np.ndarray) -> None:
        self.buf.extend(pcm16.tolist())

    def last(self, seconds: float) -> np.ndarray:
        n = int(seconds * SR)
        if len(self.buf) >= n:
            return np.asarray(list(self.buf)[-n:], dtype=np.float32) / 32768.0
        data = np.asarray(list(self.buf), dtype=np.float32) / 32768.0
        if data.size == 0:
            return np.zeros(0, dtype=np.float32)
        return np.pad(data, (n - data.size, 0)) if data.size < n else data

    def filled_seconds(self) -> float:
        return len(self.buf) / SR


def audio_capture_loop(ring: AudioRing, stop: threading.Event, sink: list) -> None:
    import numpy as np
    import pyaudiowpatch as pw
    p = pw.PyAudio()
    try:
        spk = p.get_default_wasapi_loopback()
        rate = int(spk["defaultSampleRate"])
        q: "queue.Queue[bytes]" = queue.Queue()

        def cb(in_data, frame_count, time_info, status):
            q.put(in_data)
            return (None, pw.paContinue)

        stream = p.open(format=pw.paInt16, channels=2, rate=rate, input=True,
                        input_device_index=spk["index"],
                        frames_per_buffer=int(rate * 0.2), stream_callback=cb)
        stream.start_stream()
        while not stop.is_set():
            try:
                raw = q.get(timeout=1)
            except queue.Empty:
                continue
            pcm = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).mean(axis=1)
            n = int(len(pcm) * SR / rate)
            idx = np.linspace(0, len(pcm) - 1, n)
            mono = np.interp(idx, np.arange(len(pcm)), pcm).astype(np.int16)
            ring.extend(mono)
            sink.append(mono)
        stream.stop_stream()
        stream.close()
    except Exception as exc:
        sys.stderr.write("audio_capture failed: {}\n".format(exc))
    finally:
        p.terminate()


def screen_capture_loop(out_stream, stop: threading.Event, cadence: float, change_bits: int = 14) -> None:
    import mss
    import numpy as np
    from PIL import Image
    last_hash = None
    with mss.mss() as sct:
        mon = sct.monitors[1]
        while not stop.is_set():
            t0 = time.time()
            try:
                shot = sct.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                gray = np.asarray(img.convert("L").resize((320, 180)))
                h = image_phash_small(gray)
                title = active_window_title()
                event = {"type": "screen_frame", "ts": now(), "window": title}
                if last_hash is not None:
                    d = hamming(last_hash, h)
                    event["hash_distance"] = d
                    event["changed"] = d >= change_bits
                else:
                    event["changed"] = True
                last_hash = h
                emit(out_stream, event)
            except Exception as exc:
                emit(out_stream, {"type": "screen_error", "ts": now(), "error": str(exc)[:200]})
            elapsed = time.time() - t0
            stop.wait(max(0.05, cadence - elapsed))


def music_state_loop(ring: AudioRing, out_stream, stop: threading.Event,
                     interval: float, warmup: float = 20.0) -> None:
    import librosa
    import numpy as np
    while not stop.is_set():
        stop.wait(interval)
        if ring.filled_seconds() < warmup:
            continue
        t0 = time.perf_counter()
        y = ring.last(60.0)
        mid = y[-30 * SR:]
        if float(np.sqrt(np.mean(mid ** 2))) < 1e-4:
            continue
        try:
            tempo, beats = librosa.beat.beat_track(y=mid, sr=SR)
            beats_t = librosa.frames_to_time(beats, sr=SR)
            hop = 512
            rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0]
            centroid = librosa.feature.spectral_centroid(y=y, sr=SR, hop_length=hop)[0]
            onsets = librosa.onset.onset_detect(y=mid, sr=SR, units="time")
            chroma = librosa.feature.chroma_cqt(y=mid, sr=SR).mean(axis=1)
            scores = []
            for i in range(12):
                rolled = np.roll(chroma, -i)
                scores.append(("{} major".format(NOTES[i]), float(np.corrcoef(rolled, MAJOR)[0, 1])))
                scores.append(("{} minor".format(NOTES[i]), float(np.corrcoef(rolled, MINOR)[0, 1])))
            key, key_conf = max(scores, key=lambda x: x[1])
            interval_s = float(np.median(np.diff(beats_t))) if len(beats_t) > 2 else 0.0
            event = {
                "type": "music_state", "ts": now(),
                "music": True,
                "bpm": round(float(np.atleast_1d(tempo)[0]), 1),
                "beat_phase": round(((len(beats_t) - 1) % 4) / 4, 3) if interval_s else None,
                "key": key, "key_confidence": round(key_conf, 3),
                "energy_rms": round(float(np.mean(rms)), 4),
                "energy_trend": round(float(np.mean(rms[-8 * SR // hop:]) - np.mean(rms[-16 * SR // hop:-8 * SR // hop:])), 4),
                "brightness_hz": round(float(np.mean(centroid)), 1),
                "onset_rate_per_s": round(len(onsets) / 30.0, 2),
                "analysis_s": round(time.perf_counter() - t0, 3),
            }
            emit(out_stream, event)
        except Exception as exc:
            emit(out_stream, {"type": "music_error", "ts": now(), "error": str(exc)[:200]})


class SpeechEmotionGate:
    """Lazy SER gate: drop speech events that are actually music/noise.

    Runs the DUSHA wav2vec2 model (RU) on the same tail; if the model says
    `other` (music/singing without speech-emotion) with high confidence, the
    event is suppressed. Fail-soft: any load/run error disables the gate.
    """

    MODEL = ("C:/Users/ARTEM/.cache/huggingface/hub/"
             "models--xbgoose--wavlm-base-speech-emotion-recognition-russian-dusha-finetuned/"
             "snapshots/459225f2b646e9527977e13e1324fa91c11f0166")
    LABELS = ["neutral", "angry", "positive", "sad", "other"]

    def __init__(self) -> None:
        self._ext = None
        self._model = None
        self._failed = False

    def _load(self) -> bool:
        if self._model is not None or self._failed:
            return self._model is not None
        try:
            import torch  # noqa: F401
            from transformers import Wav2Vec2FeatureExtractor, AutoModelForAudioClassification
            self._ext = Wav2Vec2FeatureExtractor(return_attention_mask=True, do_normalize=True,
                                                 feature_size=1, sampling_rate=16000, padding_value=0.0)
            self._model = AutoModelForAudioClassification.from_pretrained(self.MODEL)
            self._model.eval()
            return True
        except Exception:
            self._failed = True
            return False

    def is_speech(self, pcm: np.ndarray) -> bool:
        """True when the audio is plausibly human speech, False for music."""
        if not self._load():
            return True  # gate unavailable -> keep the event
        try:
            import torch
            inputs = self._ext(pcm, sampling_rate=16000, return_tensors="pt")
            with torch.no_grad():
                probs = torch.softmax(self._model(**inputs).logits[0], -1).tolist()
            top_label = self.LABELS[max(range(len(probs)), key=lambda i: probs[i])]
            return top_label != "other"
        except Exception:
            return True


def speech_gate_loop(ring: AudioRing, out_stream, stop: threading.Event,
                     interval: float, asr_url: str) -> None:
    """Silero VAD gate on the ring; on speech, POST the tail to whisper."""
    import io
    import urllib.request
    import wave as wavemod
    import numpy as np

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        import torch
        from silero_vad import load_silero_vad, get_speech_timestamps
        model = load_silero_vad()
    except Exception as exc:
        emit(out_stream, {"type": "speech_gate_disabled", "ts": now(), "error": str(exc)[:200]})
        return
    gate = SpeechEmotionGate()
    while not stop.is_set():
        stop.wait(interval)
        if ring.filled_seconds() < 15:
            continue
        y = ring.last(15.0)
        try:
            tensor = torch.from_numpy(y)
            stamps = get_speech_timestamps(tensor, model, sampling_rate=SR, min_speech_duration_ms=250)
            speech_s = sum((s["end"] - s["start"]) for s in stamps) / SR
            if speech_s < 1.0:
                continue
            buf = io.BytesIO()
            with wavemod.open(buf, "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(SR)
                f.writeframes((y * 32767).astype("<i2").tobytes())
            data = buf.getvalue()
            boundary = b"--sb\r\nContent-Disposition: form-data; name=\"file\"; filename=\"tail.wav\"\r\nContent-Type: audio/wav\r\n\r\n".join(
                [b"--sb\r\n", data]) + b"\r\n--sb--\r\n"
            req = urllib.request.Request(asr_url, data=boundary,
                                         headers={"Content-Type": "multipart/form-data; boundary=sb"})
            text = json.loads(urllib.request.urlopen(req, timeout=60).read()).get("text", "")
            if text.strip():
                tail = y[-10 * SR:]
                if not gate.is_speech(tail):
                    emit(out_stream, {"type": "speech_filtered", "ts": now(),
                                      "reason": "ser_other", "text_chars": len(text)})
                else:
                    emit(out_stream, {"type": "speech", "ts": now(), "speech_seconds": round(speech_s, 2),
                                      "text": text})
        except Exception as exc:
            emit(out_stream, {"type": "speech_error", "ts": now(), "error": str(exc)[:200]})


def main() -> None:
    parser = argparse.ArgumentParser(description="Streaming sensory worker prototype")
    parser.add_argument("--duration", type=int, default=0, help="seconds; 0 = until Ctrl+C")
    parser.add_argument("--out", default="runtime/sensory-events.ndjson")
    parser.add_argument("--screen-cadence", type=float, default=0.5)
    parser.add_argument("--music-cadence", type=float, default=5.0)
    parser.add_argument("--speech-cadence", type=float, default=5.0)
    parser.add_argument("--asr-url", default="http://127.0.0.1:8984/v1/audio/transcriptions")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_stream = out_path.open("a", encoding="utf-8")
    emit(out_stream, {"type": "worker_start", "ts": now(),
                      "config": {"screen_cadence": args.screen_cadence,
                                 "music_cadence": args.music_cadence,
                                 "speech_cadence": args.speech_cadence}})

    ring = AudioRing(120)
    stop = threading.Event()
    raw_sink: collections.deque = collections.deque(maxlen=120 * SR // 3200)

    threads = [
        threading.Thread(target=audio_capture_loop, args=(ring, stop, raw_sink), daemon=True),
        threading.Thread(target=screen_capture_loop, args=(out_stream, stop, args.screen_cadence), daemon=True),
        threading.Thread(target=music_state_loop, args=(ring, out_stream, stop, args.music_cadence), daemon=True),
        threading.Thread(target=speech_gate_loop, args=(ring, out_stream, stop, args.speech_cadence, args.asr_url), daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        t_start = time.time()
        while True:
            time.sleep(1)
            if args.duration and time.time() - t_start >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        time.sleep(1.5)
        try:
            wav_path = out_path.with_suffix(".wav")
            pcm = np.concatenate(list(raw_sink)) if raw_sink else np.zeros(0, dtype=np.int16)
            with wave.open(str(wav_path), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(SR)
                f.writeframes(pcm.tobytes())
        except Exception:
            pass
        emit(out_stream, {"type": "worker_stop", "ts": now(),
                          "captured_seconds": ring.filled_seconds()})
        out_stream.close()


if __name__ == "__main__":
    main()
