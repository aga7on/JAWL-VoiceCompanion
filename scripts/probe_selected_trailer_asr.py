"""Offline GigaAM/YAMNet probe for the selected Russian trailer excerpt.

The script extracts audio into a temporary directory, scores GigaAM against
the local Russian auto-caption track, and records only hashes/metrics. It does
not start capture devices, model servers, the companion, or TTS.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
CLIP = ROOT / "runtime/instances/realclip-sensory-20261024/russian-trailer.mp4"
CAPTIONS = ROOT / "runtime/instances/realclip-sensory-20261024/trailer-captions.ru.vtt"
ASR_EXE = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
ASR_MODEL = ROOT / "runtime/models/asr/gigaam-v3-e2e-rnnt-q8_0.gguf"
YAMNET_DIR = ROOT / "runtime/models/audio/yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd"
RATE = 16_000
SOURCE_START = 30.0
SOURCE_END = 40.0


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def _seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _caption_reference(path: Path) -> list[str]:
    """Read rolling VTT cues, retain inline words only through clip end."""
    source = path.read_text(encoding="utf-8-sig")
    references: list[str] = []
    cue_re = re.compile(r"(\d\d:\d\d:\d\d\.\d+) --> (\d\d:\d\d:\d\d\.\d+)")
    inline_re = re.compile(r"<(\d\d:\d\d:\d\d\.\d+)><c>(.*?)</c>", re.DOTALL)
    for block in re.split(r"\n\s*\n", source):
        lines = block.splitlines()
        if not lines:
            continue
        match = cue_re.match(lines[0])
        if not match or not SOURCE_START <= _seconds(match.group(1)) < SOURCE_END:
            continue
        if _seconds(match.group(2)) - _seconds(match.group(1)) < 0.25:
            continue
        body = " ".join(lines[1:])
        body = re.sub(r"\[[^]]*\]", " ", body)
        markers = list(inline_re.finditer(body))
        cutoff_index = next(
            (i for i, item in enumerate(markers) if _seconds(item.group(1)) >= SOURCE_END),
            len(markers),
        )
        limit = markers[cutoff_index].start() if cutoff_index < len(markers) else len(body)
        kept = body[:limit]
        if markers:
            # VTT's initial plain text is the complete current rolling cue;
            # timed fragments after it add words at specific source times.
            first = markers[0]
            prefix = body[:first.start()]
            timed = " ".join(re.sub(r"<[^>]+>", " ", m.group(2)) for m in markers[:cutoff_index])
            kept = prefix + " " + timed
        current = _tokens(re.sub(r"<[^>]+>", " ", kept))
        if not current:
            continue
        # YouTube captions repeat the complete current phrase in successive
        # cues. Remove the longest shared suffix/prefix before appending.
        overlap = 0
        for size in range(1, min(len(references), len(current)) + 1):
            if references[-size:] == current[:size]:
                overlap = size
        references.extend(current[overlap:])
    return references


def _wer(reference: list[str], hypothesis: list[str]) -> float | None:
    if not reference:
        return None
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        current = [i]
        for j, hyp in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ref != hyp)))
        previous = current
    return round(previous[-1] / len(reference), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/audio-path-replay/out/project-hail-mary-russian-trailer-asr-20261024.json")
    args = parser.parse_args()
    for path in (CLIP, CAPTIONS, ASR_EXE, ASR_MODEL, YAMNET_DIR / "yamnet.onnx", YAMNET_DIR / "yamnet_class_map.csv"):
        if not path.is_file():
            raise FileNotFoundError(path)

    with tempfile.TemporaryDirectory(prefix="jawl-selected-trailer-") as temp:
        temp_dir = Path(temp)
        wav_path = temp_dir / "audio.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(CLIP), "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(wav_path)],
            check=True, capture_output=True, timeout=60,
        )
        with wave.open(str(wav_path), "rb") as wav:
            if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) != (1, RATE, 2):
                raise RuntimeError("ffmpeg produced an unexpected audio format")
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").copy()
            duration = len(pcm) / RATE

        prefix = temp_dir / "asr"
        started = time.perf_counter()
        proc = subprocess.run(
            [str(ASR_EXE), "-m", str(ASR_MODEL), "-oj", "-of", str(prefix), str(wav_path)],
            cwd=temp_dir, capture_output=True, timeout=90, check=False,
        )
        asr_latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if proc.returncode:
            raise RuntimeError(f"GigaAM exited {proc.returncode}: {proc.stderr[-300:].decode(errors='replace')}")
        result_path = next((p for p in (temp_dir / "asr.json", temp_dir / "asr.wav.json") if p.is_file()), None)
        if result_path is None:
            raise RuntimeError("GigaAM produced no JSON")
        data = json.loads(result_path.read_text(encoding="utf-8"))
        result = data.get("transcription") or data.get("result") or data
        if isinstance(result, list):
            transcript = " ".join(str(x.get("text", "") if isinstance(x, dict) else x) for x in result)
        elif isinstance(result, dict):
            transcript = str(result.get("text") or result.get("transcription") or "")
        else:
            transcript = str(result)

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    detector = ort.InferenceSession(str(YAMNET_DIR / "yamnet.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    if detector.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError(f"YAMNet is not CPU-only: {detector.get_providers()}")
    with (YAMNET_DIR / "yamnet_class_map.csv").open(encoding="utf-8-sig", newline="") as source:
        labels = [row["display_name"] for row in csv.DictReader(source)]
    music_idx, speech_idx = labels.index("Music"), labels.index("Speech")
    windows = []
    for offset in range(0, max(1, len(pcm) - 2 * RATE + 1), RATE):
        signal = pcm[offset:offset + 2 * RATE].astype(np.float32) / 32768.0
        if len(signal) < 2 * RATE:
            signal = np.pad(signal, (0, 2 * RATE - len(signal)))
        scores = detector.run(None, {"waveform": signal.astype(np.float32)})[0].mean(axis=0)
        top = np.argsort(scores)[::-1][:5]
        windows.append({
            "start_s": round(offset / RATE, 2),
            "music_score": round(float(scores[music_idx]), 4),
            "speech_score": round(float(scores[speech_idx]), 4),
            "top_tags": [{"label": labels[int(i)], "score": round(float(scores[i]), 4)} for i in top],
        })

    reference = _caption_reference(CAPTIONS)
    hypothesis = _tokens(transcript)
    report = {
        "schema_version": 1,
        "case_id": "project_hail_mary_russian_trailer_30_40",
        "source_url": "https://www.youtube.com/watch?v=8WUnccqrs5U",
        "local_clip_sha256": hashlib.sha256(CLIP.read_bytes()).hexdigest(),
        "duration_seconds": round(duration, 3),
        "models": {
            "asr": "GigaAM v3 e2e RNNT q8_0 / CPU CLI",
            "soundscape": "YAMNet ONNX / CPUExecutionProvider",
            "cpu_only": detector.get_providers() == ["CPUExecutionProvider"],
        },
        "asr": {
            "latency_ms": asr_latency_ms,
            "reference_word_count": len(reference),
            "hypothesis_word_count": len(hypothesis),
            "auto_caption_wer": _wer(reference, hypothesis),
            "reference": "YouTube automatic Russian captions; rolling cues de-duplicated and clipped at source 40.0s",
            "reference_is_human_ground_truth": False,
            "transcript_sha256": hashlib.sha256(" ".join(hypothesis).encode("utf-8")).hexdigest(),
            "transcript_text_persisted": False,
        },
        "yamnet": {
            "window_seconds": 2,
            "hop_seconds": 1,
            "windows": windows,
            "music_windows_ge_0_30": sum(row["music_score"] >= 0.30 for row in windows),
        },
        "raw_audio_persisted": False,
        "limitations": [
            "The caption track is machine-generated and is not human ground truth.",
            "One 10-second trailer excerpt cannot establish general Russian ASR accuracy.",
            "YAMNet Music scores are diagnostic only and are not accepted as genre or mood labels.",
            "This offline replay does not test live capture-to-companion freshness or joint AV grounding.",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "wer": report["asr"]["auto_caption_wer"], "reference_words": len(reference), "hypothesis_words": len(hypothesis), "asr_ms": asr_latency_ms, "music_windows": report["yamnet"]["music_windows_ge_0_30"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
