"""GigaAM (canonical ASR) baseline on the same RU fixtures as the R2T2 smoke.

Runs the project's own CrispASRFileTranscriber so the comparison uses the
canonical code path, not a reimplementation. With --expects the harness becomes
a quality gate: every case whose manifest entry demands speech
(``must_transcribe``) must produce at least ``min_chars`` characters. When an
expectation includes ``reference_text`` and ``max_wer``, the transcript is also
scored; ``must_be_empty`` cases enforce abstention. A gate failure exits non-zero.

Usage:
  python -X utf8 scripts/gigaam_baseline_fixtures.py [wav ...]
  python -X utf8 scripts/gigaam_baseline_fixtures.py --expects cases.json [wav ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

REPO = Path(r"G:\AI\JAWL-VoiceCompanion")
sys.path.insert(0, str(REPO / "src"))

from jawl_voicecompanion.giga_final import CrispASRFileTranscriber  # noqa: E402

CRISPASR = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
# The GigaAM weights live inside the project (runtime/models/asr, gitignored)
# so a dev-machine cleanup of external model dirs cannot break the canonical
# ASR engine (ADR-044: GigaAM is the only ASR; a missing model must fail
# loudly, not silently switch engines).
MODEL = REPO / "runtime" / "models" / "asr" / "gigaam-v3-e2e-rnnt-q8_0.gguf"

DEFAULT_WAVS = [
    REPO / "runtime" / "voice-native-ru-clean-20260906.wav",
    REPO / "runtime" / "voice-native-command-20260906.wav",
    REPO / "runtime" / "bench" / "rumbench_ru" / "ref_ru.wav",
]


def load_expectations(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"expectations manifest has no case list: {path}")
    table: dict[str, dict] = {}
    for case in cases:
        if isinstance(case, dict) and case.get("file"):
            table[str(case["file"])] = case
    if not table:
        raise ValueError(f"expectations manifest is empty: {path}")
    return table


def _normalize_for_scoring(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def _edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, start=1):
        current = [i]
        for j, right_item in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left_item != right_item),
            ))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Return WER after Unicode normalization and punctuation-insensitive tokenization."""
    ref = _normalize_for_scoring(reference)
    hyp = _normalize_for_scoring(hypothesis)
    if not ref:
        raise ValueError("WER reference must contain at least one word")
    return _edit_distance(ref, hyp) / len(ref)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wavs", nargs="*", help="WAV files to transcribe")
    parser.add_argument("--expects", type=Path, default=None,
                        help="cases.json manifest; turns the run into a quality gate")
    parser.add_argument("--json-report", type=Path, default=None,
                        help="write the per-file results as JSON")
    args = parser.parse_args()

    expectations: dict[str, dict] = {}
    if args.expects is not None:
        if not args.expects.exists():
            print(f"expectations manifest not found: {args.expects}", file=sys.stderr)
            return 2
        expectations = load_expectations(args.expects)

    wavs = [Path(item) for item in args.wavs] or DEFAULT_WAVS
    for path, label in ((CRISPASR, "crispasr"), (MODEL, "gigaam model")):
        if not path.exists():
            print(f"{label} not found: {path}", file=sys.stderr)
            return 2
    transcriber = CrispASRFileTranscriber(str(CRISPASR), str(MODEL))

    gate_mode = bool(expectations)
    print(f"gigaam={MODEL.name} gate={gate_mode}")
    results: list[dict] = []
    failures: list[str] = []
    for wav in wavs:
        if not wav.exists():
            print(f"== {wav.name} MISSING")
            if gate_mode:
                failures.append(f"{wav.name}: file missing")
            continue
        expectation = expectations.get(wav.name)
        payload = wav.read_bytes()
        t0 = time.perf_counter()
        text = ""
        error = None
        try:
            text = transcriber.transcribe(payload)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        dt = time.perf_counter() - t0
        entry = {
            "file": wav.name,
            "seconds": round(dt, 3),
            "chars": len(text),
            "text": text,
            "error": error,
        }
        if gate_mode:
            if expectation is None:
                # Not covered by the manifest: the harness was invoked over a
                # wider directory than the manifest describes. Fail closed.
                failures.append(f"{wav.name}: no expectation in manifest")
                entry["gate"] = "no_expectation"
            else:
                must = bool(expectation.get("must_transcribe"))
                minimum = int(expectation.get("min_chars") or 0)
                reference = expectation.get("reference_text")
                max_wer = expectation.get("max_wer")
                if must and (error or len(text) < max(1, minimum)):
                    detail = f"must_transcribe but got {len(text)} chars" + (
                        f" (error: {error})" if error else "")
                    failures.append(f"{wav.name}: {detail}")
                    entry["gate"] = "failed"
                elif must and reference is not None and max_wer is not None:
                    measured_wer = word_error_rate(str(reference), text)
                    entry["reference_text"] = str(reference)
                    entry["wer"] = round(measured_wer, 4)
                    entry["max_wer"] = float(max_wer)
                    if measured_wer > float(max_wer):
                        failures.append(
                            f"{wav.name}: WER {measured_wer:.3f} exceeds {float(max_wer):.3f}"
                        )
                        entry["gate"] = "failed_wer"
                    else:
                        entry["gate"] = "ok_wer"
                elif bool(expectation.get("must_be_empty")) and (error is None and text.strip()):
                    failures.append(f"{wav.name}: expected empty transcript, got {len(text)} chars")
                    entry["gate"] = "failed_nonempty"
                elif bool(expectation.get("must_be_empty")):
                    entry["gate"] = "ok_empty"
                elif not must and error is None and not text:
                    # Tolerated no-speech case that stayed empty: correct.
                    entry["gate"] = "ok_empty"
                elif not must and error:
                    # The engine errors on noise: tolerated, but recorded.
                    entry["gate"] = "ok_tolerated_error"
                else:
                    entry["gate"] = "ok"
                entry["expected_min_chars"] = max(1, minimum) if must else 0
                if must and reference is None:
                    entry["quality_gate"] = "presence_only"
                elif must and max_wer is None:
                    entry["quality_gate"] = "presence_only"
                elif must:
                    entry["quality_gate"] = "wer"
        results.append(entry)
        status_line = f"== {wav.name} ({dt:.1f}s)"
        if entry.get("gate"):
            status_line += f" [{entry['gate']}]"
        if entry.get("wer") is not None:
            status_line += f" WER={entry['wer']:.3f}"
        print(status_line)
        print(f"   {text}" if text else (f"   ERROR: {error}" if error else "   (empty)"))

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps(
                {"schema_version": 1, "gate_mode": gate_mode,
                 "files": results, "failures": failures,
                 "pass": not failures},
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"report: {args.json_report}")

    if gate_mode:
        print(f"gate: {'PASS' if not failures else 'FAIL'} ({len(failures)} failures)")
        for failure in failures:
            print(f"  ! {failure}")
        return 0 if not failures else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
