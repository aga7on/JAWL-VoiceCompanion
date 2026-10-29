"""Paired EG2 audio-path replay on the frozen A09/A12/A14/A16/A17 fixtures.

This compares the current direct classifier with the validated ambient
AudioDescriptionService boundary. It does not capture devices or persist PCM.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_sensory_case_simulation import AUDIO_DIR, make_cases, wav_bytes  # noqa: E402
from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge  # noqa: E402
from jawl_voicecompanion.audio_understanding import AudioDescriptionService  # noqa: E402
from jawl_voicecompanion.eg2_describer import (  # noqa: E402
    DetailedSensoryDescriber,
    Eg2AudioDescriptionProvider,
)
from jawl_voicecompanion.eg2_sensory import (  # noqa: E402
    DEFAULT_EG2_ONNX_ROOT,
    EmbeddingGemmaSensoryCortex,
)


SOAK_REPORT = ROOT / "runtime" / "sensory-case-simulation-20261024-clean.json"
CASE_IDS = (
    "A09-russian-speech-1",
    "A12-short-phrase-pause",
    "A14-quiet-speech",
    "A16-noise-only-negative",
    "A17-silence-negative",
)
SOURCE_INFO: dict[str, dict[str, Any]] = {
    "A09-russian-speech-1": {
        "group": "speech-question-01",
        "parent": "question-01.wav",
        "transform": "read_wav/downmix-if-stereo/re-encode-mono-pcm16",
    },
    "A12-short-phrase-pause": {
        "group": "speech-question-01",
        "parent": "question-01.wav",
        "transform": "speech-question-01 plus 0.5s generated zero PCM, then mono PCM16 re-encode",
    },
    "A14-quiet-speech": {
        "group": "speech-question-01",
        "parent": "question-01.wav",
        "transform": "speech-question-01 attenuated by -18 dB, then mono PCM16 re-encode",
    },
    "A16-noise-only-negative": {
        "group": "synthetic-noise-seed-16",
        "parent": None,
        "transform": "2s Gaussian noise, seed=16, sigma=700 PCM counts",
    },
    "A17-silence-negative": {
        "group": "exact-zero-pcm-control",
        "parent": None,
        "transform": "2s exact digital zero at source sample rate",
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wav_from_pcm16(pcm16: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16)
    return output.getvalue()


def _normalize_case_wav(wav_data: bytes) -> tuple[bytes, dict[str, Any]]:
    with wave.open(io.BytesIO(wav_data), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        if sample_width != 2 or channels not in (1, 2):
            raise ValueError("fixture must be 16-bit PCM WAV with one or two channels")
        source_pcm = wav.readframes(frame_count)
    normalized = AmbientAudioASRBridge._to_target_pcm(
        source_pcm, sample_rate, channels, 16000
    )
    return normalized, {
        "input_sample_rate": sample_rate,
        "input_channels": channels,
        "input_sample_width_bytes": sample_width,
        "input_duration_seconds": frame_count / sample_rate,
        "normalized_sample_rate": 16000,
        "normalized_channels": 1,
        "normalized_sample_width_bytes": 2,
        "normalized_duration_seconds": len(normalized) / 2 / 16000,
        "normalization": "same AmbientAudioASRBridge._to_target_pcm converter used at ambient ingress",
    }


def _quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int((len(ordered) - 1) * quantile)
    return round(ordered[index], 3)


def _soak_gate(report_path: Path) -> tuple[dict[str, Any], str]:
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes.decode("utf-8"))
    if report.get("status") != "passed" or report.get("error_count") != 0:
        raise RuntimeError("paired replay requires a passed terminal soak with zero errors")
    if not report.get("finished_at") or int(report.get("batch_count", 0)) < 1:
        raise RuntimeError("soak report lacks terminal metadata")

    import psutil

    active: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "run_sensory_case_simulation.py" in command or "Qwen3.5-0.8B-Q4_K_M.gguf" in command:
            active.append({"pid": process.info.get("pid"), "name": process.info.get("name")})
    if active:
        raise RuntimeError(f"sensory soak workers still appear active: {active}")
    return report, _sha256(report_bytes)


def _call_direct(cortex: EmbeddingGemmaSensoryCortex, wav_data: bytes) -> tuple[dict[str, Any], float, float]:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    observation = cortex.classify_audio_wav(wav_data)
    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    cpu_ms = (time.process_time() - cpu_start) * 1000.0
    return observation.to_dict(), wall_ms, cpu_ms


def _call_ambient(
    service: AudioDescriptionService,
    describer: DetailedSensoryDescriber,
    pcm16: bytes,
    clip_id: str,
) -> tuple[dict[str, Any], dict[str, Any], float, float]:
    raw_detail: dict[str, Any] = {}
    original = describer.describe_audio_pcm16

    def tapped(pcm: bytes, *, sample_rate: int = 16000, channels: int = 1):
        observation = original(pcm, sample_rate=sample_rate, channels=channels)
        raw_detail["value"] = observation.to_dict()
        return observation

    describer.describe_audio_pcm16 = tapped  # type: ignore[method-assign]
    try:
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        result = service.describe(
            pcm16,
            sample_rate=16000,
            channels=1,
            clip_id=clip_id,
        )
        wall_ms = (time.perf_counter() - wall_start) * 1000.0
        cpu_ms = (time.process_time() - cpu_start) * 1000.0
    finally:
        describer.describe_audio_pcm16 = original  # type: ignore[method-assign]
    if "value" not in raw_detail:
        raise RuntimeError("ambient raw diagnostic observation was not captured")
    return result, raw_detail["value"], wall_ms, cpu_ms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soak-report", type=Path, default=SOAK_REPORT)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20 or not 0 <= args.warmup <= 5:
        parser.error("repeats must be 1..20 and warmup must be 0..5")

    soak, soak_sha256 = _soak_gate(args.soak_report)
    if not (DEFAULT_EG2_ONNX_ROOT / "onnx" / "audio_encoder_q4.onnx").is_file():
        raise FileNotFoundError("EmbeddingGemma audio ONNX model is unavailable")

    case_by_id = {case["id"]: case for case in make_cases()}
    normalized: dict[str, dict[str, Any]] = {}
    for case_id in CASE_IDS:
        case = case_by_id[case_id]
        pcm16, audio_format = _normalize_case_wav(case["wav"])
        source_info = SOURCE_INFO[case_id]
        source_path = AUDIO_DIR / source_info["parent"] if source_info["parent"] else None
        parent_hash = _sha256(source_path.read_bytes()) if source_path and source_path.is_file() else None
        normalized[case_id] = {
            "wav": _wav_from_pcm16(pcm16, 16000),
            "pcm16": pcm16,
            "meta": {
                "id": case_id,
                "truth": case.get("truth", []),
                "source_group": source_info["group"],
                "parent_recording": source_info["parent"],
                "parent_sha256": parent_hash,
                "case_wav_sha256": _sha256(case["wav"]),
                "normalized_pcm_sha256": _sha256(pcm16),
                "normalized_wav_sha256": _sha256(_wav_from_pcm16(pcm16, 16000)),
                "transform": source_info["transform"],
                "format": audio_format,
            },
        }

    cortex = EmbeddingGemmaSensoryCortex(DEFAULT_EG2_ONNX_ROOT, load_vision=False)
    describer = DetailedSensoryDescriber(cortex)
    service = AudioDescriptionService(Eg2AudioDescriptionProvider(describer))
    try:
        providers = cortex.audio_session.get_providers()
        if "CPUExecutionProvider" not in providers:
            raise RuntimeError(f"CPUExecutionProvider missing from EG2 audio session: {providers}")

        warmup_rows = []
        for index in range(args.warmup):
            first = normalized[CASE_IDS[index % len(CASE_IDS)]]
            direct, direct_wall, _ = _call_direct(cortex, first["wav"])
            ambient, ambient_raw, ambient_wall, _ = _call_ambient(
                service, describer, first["pcm16"], f"warmup-{index}"
            )
            warmup_rows.append({
                "case_id": CASE_IDS[index % len(CASE_IDS)],
                "direct_latency_ms": round(direct_wall, 3),
                "ambient_latency_ms": round(ambient_wall, 3),
                "direct_label": direct.get("top_label"),
                "ambient_kind": ambient.get("kind"),
                "ambient_raw_level0": ambient_raw.get("level0"),
            })

        soak_cases = {
            case.get("id"): case
            for case in (soak.get("batches", [])[-1].get("cases", []) if soak.get("batches") else [])
        }
        results = []
        latency_by_path: dict[str, list[float]] = {"direct": [], "ambient": []}
        cpu_by_path: dict[str, list[float]] = {"direct": [], "ambient": []}
        for case_index, case_id in enumerate(CASE_IDS):
            inputs = normalized[case_id]
            direct_calls = []
            ambient_calls = []
            for repeat in range(args.repeats):
                methods = ("direct", "ambient") if (case_index + repeat) % 2 == 0 else ("ambient", "direct")
                call_results: dict[str, Any] = {}
                for method in methods:
                    if method == "direct":
                        output, wall_ms, cpu_ms = _call_direct(cortex, inputs["wav"])
                        call_results[method] = {
                            "output": output,
                            "wall_latency_ms": round(wall_ms, 3),
                            "process_cpu_ms": round(cpu_ms, 3),
                            "input_pcm_sha256": inputs["meta"]["normalized_pcm_sha256"],
                        }
                    else:
                        output, raw, wall_ms, cpu_ms = _call_ambient(
                            service, describer, inputs["pcm16"], case_id
                        )
                        call_results[method] = {
                            "output": output,
                            "raw_detailed_observation": raw,
                            "wall_latency_ms": round(wall_ms, 3),
                            "process_cpu_ms": round(cpu_ms, 3),
                            "input_pcm_sha256": inputs["meta"]["normalized_pcm_sha256"],
                        }
                direct_calls.append(call_results["direct"])
                ambient_calls.append(call_results["ambient"])
                latency_by_path["direct"].append(call_results["direct"]["wall_latency_ms"])
                latency_by_path["ambient"].append(call_results["ambient"]["wall_latency_ms"])
                cpu_by_path["direct"].append(call_results["direct"]["process_cpu_ms"])
                cpu_by_path["ambient"].append(call_results["ambient"]["process_cpu_ms"])

            baseline = soak_cases.get(case_id, {})
            results.append({
                "input": inputs["meta"],
                "soak_regression_evidence": {
                    "status": baseline.get("status"),
                    "audio_tag": baseline.get("audio_tag"),
                    "audio_score": baseline.get("audio_score"),
                    "audio_latency_ms": baseline.get("audio_latency_ms"),
                    "asr_nonempty": baseline.get("asr_nonempty"),
                    "asr_chars": baseline.get("asr_chars"),
                    "asr_sha256": baseline.get("asr_sha256"),
                    "scope": "one final-batch fixture record; repeated soak batches are not independent samples",
                },
                "measured_repeats": args.repeats,
                "direct_calls": direct_calls,
                "ambient_calls": ambient_calls,
            })

        import psutil

        report = {
            "schema_version": 1,
            "status": "passed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "method": "paired same normalized PCM16 mono 16kHz; direct classifier vs validated ambient service",
            "scope": "five existing synthetic/derived soak fixtures; regression comparison, not independent accuracy estimation",
            "soak": {
                "report_path": str(args.soak_report.relative_to(ROOT)),
                "report_sha256": soak_sha256,
                "status": soak.get("status"),
                "elapsed_seconds": soak.get("elapsed_seconds"),
                "batch_count": soak.get("batch_count"),
                "error_count": soak.get("error_count"),
                "finished_at": soak.get("finished_at"),
            },
            "runtime": {
                "python": sys.version,
                "os": os.name,
                "model_root": str(DEFAULT_EG2_ONNX_ROOT),
                "audio_session_providers": providers,
                "process_rss_bytes_after": psutil.Process().memory_info().rss,
                "warmup_count_per_path": args.warmup,
                "repeats_per_case_per_path": args.repeats,
                "timing_note": "wall and process CPU timings exclude normalization; per-call repeats are latency repeats, not independent clips",
            },
            "warmups": warmup_rows,
            "latency_summary_ms": {
                path: {
                    "n_calls": len(values),
                    "p50": _quantile(values, 0.50),
                    "p95": _quantile(values, 0.95),
                    "max": round(max(values), 3) if values else None,
                }
                for path, values in latency_by_path.items()
            },
            "process_cpu_summary_ms": {
                path: {
                    "n_calls": len(values),
                    "p50": _quantile(values, 0.50),
                    "p95": _quantile(values, 0.95),
                    "max": round(max(values), 3) if values else None,
                }
                for path, values in cpu_by_path.items()
            },
            "source_group_counts": {
                key: sum(1 for row in results if row["input"]["source_group"] == key)
                for key in sorted({row["input"]["source_group"] for row in results})
            },
            "results": results,
            "limitations": [
                "A09/A12/A14 share one parent speech recording; they are three transforms, not three independent speakers.",
                "A16 is deterministic generated Gaussian noise and A17 is one exact digital-silence control.",
                "The ambient service exposes bounded schema output; raw DetailedObservation was tapped from the same service invocation for diagnostics.",
                "This path-only replay does not include AmbientAudioASRBridge segmentation, ASR, live loopback capture, memory ingestion, or user-facing fusion timing.",
                "No accuracy, calibration, or generalization rate is inferred from these five fixed inputs.",
            ],
            "raw_pcm_persisted": False,
            "raw_audio_persisted": False,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temp_path = args.report.with_suffix(args.report.suffix + ".tmp")
        temp_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(args.report)
    finally:
        describer.close()

    print(json.dumps({
        "status": report["status"],
        "report": str(args.report),
        "cases": len(results),
        "p50_ms": {path: values["p50"] for path, values in report["latency_summary_ms"].items()},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
