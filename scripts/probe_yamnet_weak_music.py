from __future__ import annotations

import csv
import json
import subprocess
import sys
import wave
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.yamnet_soundscape import YamnetSoundscapeDetector, MUSIC_THRESHOLD, MUSIC_HYPOTHESIS_THRESHOLD


def read_wav(path: Path):
    with wave.open(str(path), "rb") as f:
        if f.getsampwidth() != 2:
            raise ValueError(f"expected PCM16 WAV: {path.name}")
        return f.readframes(f.getnframes()), f.getframerate(), f.getnchannels()


def decode_mp3(path: Path):
    p = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-t", "4", "-f", "s16le",
        "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", "pipe:1",
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout, 16000, 1


def evaluate(detector, cohort, name, label, clip, pcm, rate, channels):
    result = detector.describe(pcm, sample_rate=rate, channels=channels, clip_id=name)
    return {
        "cohort": cohort,
        "name": name,
        "label": label,
        "kind": result.get("kind"),
        "windows": result.get("windows", 0),
        "music_windows": result.get("music_windows", 0),
        "music_score_max": result.get("music_score_max"),
        "music_score_median": result.get("music_score_median"),
        "weak_music_candidate": result.get("music_hypothesis") is not None,
        "confirmed_music": result.get("kind") == "music",
        "duration_s": result.get("duration_seconds"),
    }


def normalize_rms(samples: np.ndarray, target: float = 0.10) -> np.ndarray:
    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
    return samples.astype(np.float32) * (target / max(rms, 1e-8))


def decode_wav_float(detector, path: Path) -> np.ndarray:
    pcm, rate, channels = read_wav(path)
    return detector._to_mono_16k(pcm, rate, channels)


def mix_speech_music(speech: np.ndarray, music: np.ndarray, speech_over_music_db: float) -> np.ndarray:
    count = max(len(speech), len(music))
    voice = np.pad(normalize_rms(speech), (0, max(0, count - len(speech))))[:count]
    bed = np.pad(normalize_rms(music), (0, max(0, count - len(music))))[:count]
    bed *= 10.0 ** (-speech_over_music_db / 20.0)
    mixed = voice + bed
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.95:
        mixed *= 0.95 / peak
    pcm16 = (np.clip(mixed, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    return pcm16


def main():
    detector = YamnetSoundscapeDetector()
    if detector.session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("expected CPUExecutionProvider only")
    rows = []
    for fold in (3, 4, 5):
        folder = ROOT / f"runtime/audio-path-replay/esc10-fold{fold}"
        with (folder / "manifest.csv").open(encoding="utf-8-sig", newline="") as f:
            manifest = list(csv.DictReader(f))
        for item in manifest:
            if item.get("fold") != str(fold):
                raise ValueError(f"fold mismatch in {folder / 'manifest.csv'}")
            wav_path = folder / item["filename"]
            pcm, rate, channels = read_wav(wav_path)
            rows.append(evaluate(detector, "esc10_nonmusic", wav_path.name, item["category"], None, pcm, rate, channels))

    fma_manifest = json.loads((ROOT / "runtime/audio-path-replay/data/fma-medium-selected/manifest.json").read_text(encoding="utf-8"))
    music_sources = {}
    for item in fma_manifest["tracks"]:
        mp3 = ROOT / item["local_file"]
        pcm, rate, channels = decode_mp3(mp3)
        rows.append(evaluate(detector, "fma_music_positive", mp3.name, item["genre"], None, pcm, rate, channels))
        if item["track_id"] in {34312, 21855, 107568, 7484, 50970, 1382}:
            music_sources[item["genre"]] = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0

    speech_sources = {}
    for index in range(1, 4):
        wav_path = ROOT / f"runtime/synthetic-questions/question-{index:02d}.wav"
        speech = decode_wav_float(detector, wav_path)
        speech_sources[f"speech_query_{index:02d}"] = speech
        pcm16 = (np.clip(speech, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        rows.append(evaluate(detector, "recorded_speech_only", wav_path.name, "speech_query", None, pcm16, 16000, 1))
    for speech_name, speech in speech_sources.items():
        for genre, music in music_sources.items():
            for snr_db in (10, 0, -10):
                pcm16 = mix_speech_music(speech, music, snr_db)
                row = evaluate(
                    detector,
                    "speech_plus_music_mix",
                    f"{speech_name}__{genre}__speech_over_music_{snr_db}db",
                    genre,
                    None,
                    pcm16,
                    16000,
                    1,
                )
                row["speech_over_music_db"] = snr_db
                rows.append(row)

    synthetic_root = ROOT / "runtime/synthetic-cases"
    for name, label in (("source.wav", "synthetic_tera_speech"), ("cases/noise_only.wav", "white_noise_only"), ("cases/noisy_snr0.wav", "speech_masked_by_noise"), ("cases/noisy_snr10.wav", "speech_plus_noise")):
        pcm, rate, channels = read_wav(synthetic_root / name)
        rows.append(evaluate(detector, "synthetic_controls", name, label, None, pcm, rate, channels))

    real_media_root = ROOT / "runtime/multimodal-realclips-20261024/probes/lowrate"
    for name, label in (
        ("01_ru_trailer.wav", "russian_trailer"),
        ("02_anime.wav", "anime_trailer"),
        ("03_gameplay.wav", "gameplay"),
        ("04_coding_ui.wav", "coding_video"),
        ("05_aqua_song.wav", "song_clip"),
    ):
        pcm, rate, channels = read_wav(real_media_root / name)
        rows.append(evaluate(detector, "real_media_clips", name, label, None, pcm, rate, channels))

    summary = {}
    groups = defaultdict(list)
    for row in rows:
        groups[row["cohort"]].append(row)
    for cohort, group in groups.items():
        summary[cohort] = {
            "count": len(group),
            "weak_music_candidates": sum(row["weak_music_candidate"] for row in group),
            "confirmed_music": sum(row["confirmed_music"] for row in group),
            "candidate_by_label": dict(sorted(Counter(row["label"] for row in group if row["weak_music_candidate"]).items())),
            "score_max_median": sorted((row["music_score_max"] for row in group if isinstance(row["music_score_max"], (int, float))))[len([row for row in group if isinstance(row["music_score_max"], (int, float))]) // 2] if any(isinstance(row["music_score_max"], (int, float)) for row in group) else None,
        }
    for snr_db in (10, 0, -10):
        group = [row for row in rows if row.get("cohort") == "speech_plus_music_mix" and row.get("speech_over_music_db") == snr_db]
        summary.setdefault("speech_plus_music_by_snr_db", {})[str(snr_db)] = {
            "count": len(group),
            "weak_music_candidates": sum(row["weak_music_candidate"] for row in group),
            "confirmed_music": sum(row["confirmed_music"] for row in group),
            "any_music_signal": sum(row["weak_music_candidate"] or row["confirmed_music"] for row in group),
        }
    out = {
        "schema_version": 1,
        "model": detector.name,
        "cpu_only": True,
        "providers": detector.session.get_providers(),
        "threads": {"intra_op": 1, "inter_op": 1},
        "confirmed_music_threshold": MUSIC_THRESHOLD,
        "weak_candidate_routing_cutoff": MUSIC_HYPOTHESIS_THRESHOLD,
        "weak_cutoff_is_calibrated": False,
        "raw_audio_persisted": False,
        "transcript_persisted": False,
        "summary": summary,
        "clips": rows,
    }
    path = ROOT / "runtime/audio-path-replay/out/yamnet-weak-music-candidate-20261029.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(path)


if __name__ == "__main__":
    main()
