"""Evaluate YAMNet's candidate lane on a source-deduplicated CC BY ESC-10 fold.

Fold-5 files and manifest are expected under ignored runtime/audio-path-replay.
The result contains labels/scores only; it never copies PCM into the artifact.
"""
from __future__ import annotations

import json
import sys
import wave
import csv
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import jawl_voicecompanion.yamnet_soundscape as yamnet_module

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.yamnet_soundscape import YamnetSoundscapeDetector  # noqa: E402


TRUTH_LABELS = {
    "dog": ("Dog",),
    "crying_baby": ("Crying, sobbing", "Baby cry, infant cry"),
    "helicopter": ("Helicopter",),
    "chainsaw": ("Chainsaw",),
    "rain": ("Rain", "Rain on surface"),
    "crackling_fire": ("Crackling fire", "Fire"),
    "sneezing": ("Sneeze", "Sneeze, snort"),
    "rooster": ("Rooster", "Crowing, cock-a-doodle-doo"),
    "sea_waves": ("Waves, surf", "Ocean", "Sea"),
    "clock_tick": ("Clock", "Tick", "Tick-tock"),
}


def read_clip(path: Path) -> tuple[bytes, int, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"expected PCM16 WAV: {path.name}")
        return source.readframes(source.getnframes()), source.getframerate(), source.getnchannels()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    data_dir = ROOT / f"runtime/audio-path-replay/esc10-fold{args.fold}"
    clip_dir = data_dir
    detector = YamnetSoundscapeDetector()
    production_event_threshold = yamnet_module.EVENT_THRESHOLD
    if detector.session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("probe must remain CPU-only")
    with (data_dir / "manifest.csv").open(encoding="utf-8-sig", newline="") as manifest_file:
        cases = list(csv.DictReader(manifest_file))
    if not cases or any(row.get("fold") != str(args.fold) for row in cases):
        raise ValueError(f"expected source-deduplicated ESC-10 fold {args.fold} manifest")

    results = []
    row_scores = []
    for row_meta in cases:
        truth, filename = row_meta["category"], row_meta["filename"]
        pcm, rate, channels = read_clip(clip_dir / filename)
        result = detector.describe(pcm, sample_rate=rate, channels=channels, clip_id=filename)
        waveform = detector._to_mono_16k(pcm, rate, channels)
        per_window: list[np.ndarray] = []
        window_size, hop = 2 * 16000, 16000
        for start in range(0, max(1, len(waveform) - window_size + hop), hop):
            frame = waveform[start : start + window_size]
            if len(frame) < window_size:
                frame = np.pad(frame, (0, window_size - len(frame)))
            per_window.append(np.asarray(detector.session.run(
                None, {"waveform": frame.astype(np.float32)}
            )[0], dtype=np.float32).mean(axis=0).reshape(-1))
        recurrent: Counter[str] = Counter()
        maxima: dict[str, float] = {}
        for row in per_window:
            for idx in np.argsort(row)[::-1][:5]:
                label, score = detector.labels[int(idx)], float(row[int(idx)])
                if score >= 0.10:
                    recurrent[label] += 1
                    maxima[label] = max(maxima.get(label, 0.0), score)
        top = [
            {"label": label, "window_hits": hits, "max_score": round(maxima[label], 4)}
            for label, hits in recurrent.most_common(5)
        ]
        required_hits = 2
        truth_support = []
        for label in TRUTH_LABELS.get(truth, ()):
            if label not in detector.labels:
                continue
            index = detector.labels.index(label)
            hits = sum(float(scores[index]) >= 0.10 for scores in per_window)
            if hits >= required_hits:
                truth_support.append({"label": label, "window_hits": hits})
        results.append({
            "truth": truth,
            "file": filename,
            "music_kind": result["kind"],
            "candidate_events": result["event_candidates"],
            "truth_label_support": truth_support,
            "top_recurrent_labels": top,
            "windows": len(per_window),
        })
        row_scores.append(per_window)

    # Compare candidate cutoffs without another ONNX inference pass. These are
    # exploratory operating points, not fitted/calibrated probabilities.
    threshold_sweep = []
    for threshold in (0.10, 0.15, 0.20, 0.25, 0.30):
        yamnet_module.EVENT_THRESHOLD = threshold
        emitted = correct = clips_with_candidate = clips_with_exact = 0
        for metadata, scores in zip(cases, row_scores):
            candidates = detector._event_candidates(scores, required_hits=2)
            truth = metadata["category"]
            accepted = set(TRUTH_LABELS.get(truth, ()))
            labels = [item["label"] for item in candidates]
            emitted += len(labels)
            correct += sum(label in accepted for label in labels)
            clips_with_candidate += bool(labels)
            clips_with_exact += any(label in accepted for label in labels)
        threshold_sweep.append({
            "raw_score_cutoff": threshold,
            "clips_with_candidate": clips_with_candidate,
            "clips_with_exact_category_label": clips_with_exact,
            "emitted_labels": emitted,
            "exact_category_labels": correct,
            "label_precision_on_this_fold": round(correct / emitted, 4) if emitted else None,
        })
    yamnet_module.EVENT_THRESHOLD = production_event_threshold

    output = {
        "schema_version": 1,
        "dataset": "ESC-10 subset of ESC-50",
        "dataset_url": "https://github.com/karolpiczak/ESC-50",
        "license": "CC BY (ESC-10 subset, per upstream README)",
        "fold": args.fold,
        "selection": f"one unique source recording from each ESC-10 row in fold {args.fold}",
        "model": detector.name,
        "cpu_only": True,
        "raw_audio_persisted": False,
        "scores_are_calibrated": False,
        "threshold_sweep_is_exploratory_not_calibration": True,
        "production_event_score_cutoff": production_event_threshold,
        "threshold_sweep": threshold_sweep,
        "clips": results,
    }
    target = ROOT / f"runtime/audio-path-replay/out/yamnet-esc10-fold{args.fold}-20261029.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in results:
        print(f"{row['truth']:12} {row['file']:24} candidates={row['candidate_events']} top={row['top_recurrent_labels'][:3]}")
    categories = sorted(TRUTH_LABELS)
    print("Raw truth-label support by category (diagnostic score >= 0.10):")
    for category in categories:
        matches = [row for row in results if row["truth"] == category]
        supported = sum(bool(row["truth_label_support"]) for row in matches)
        print(f"  {category}: {supported}/{len(matches)}")
    print("Candidate threshold sweep (labels match exact ESC-10 class taxonomy only):")
    for item in threshold_sweep:
        print(f"  {item['raw_score_cutoff']:.2f}: exact clips {item['clips_with_exact_category_label']}/{len(results)}; "
              f"label precision {item['exact_category_labels']}/{item['emitted_labels']} "
              f"({item['label_precision_on_this_fold']})")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
