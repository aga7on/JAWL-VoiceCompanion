# -*- coding: utf-8 -*-
"""Temporal Evidence Verifier for Retrospective Visual Observations.

Cycle 05 / Round 12.1 (H12.1 P0) — AC-06, AC-07, AC-02, AC-08:
Decouples raw model interpretations (MODEL_OBSERVATION) from verified facts
(VERIFIED_FACT).

Prevents elevating single-pass VLM hallucinations to factual status in episodic
memory without independent deterministic verification (Windows OCR, spatial telemetry,
or multi-signal consensus).

Statuses:
  - MODEL_OBSERVATION: Raw unverified interpretation of the visual model.
  - VERIFIED_FACT: Claim independently confirmed by deterministic signals (e.g. OCR match).
  - UNVERIFIED: Insufficient independent evidence available; fact promotion denied.
  - CONTRADICTED: Independent signals actively disagree with model hypothesis.
  - SOURCE_UNAVAILABLE: Underlying video frame, interval, or ROI is inaccessible or corrupt.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image

# Canonical Verification Statuses
VERIFIED_FACT = "verified_fact"
MODEL_OBSERVATION = "model_observation"
UNVERIFIED = "unverified"
CONTRADICTED = "contradicted"
SOURCE_UNAVAILABLE = "source_unavailable"

ALL_VERIFICATION_STATUSES = frozenset({
    VERIFIED_FACT,
    MODEL_OBSERVATION,
    UNVERIFIED,
    CONTRADICTED,
    SOURCE_UNAVAILABLE,
})

GENERIC_STOPWORDS = frozenset({
    "система", "игрок", "квест", "уведомление", "сообщение", "событие", "кадр",
    "число", "точка", "предмет", "код", "чат", "в", "на", "таймкод", "номер",
    "секунд", "секунды", "время", "frame", "обнаружено", "обнаружен", "overview",
    "live", "combat", "chat", "финальное", "объявила", "найден", "отсутствует",
})

_CREATE_NO_WINDOW = 0x08000000


@dataclass
class VerificationResult:
    """Detailed outcome of independent retrospective evidence verification."""

    verification_status: str
    is_verified_fact: bool
    verifier_kind: str
    reason: str
    verified_answer: str
    independent_claim: str
    confidence: float
    source_frame_id: int = -1
    pts_us: int = -1
    roi: list[int] | None = None
    segment_id: int = 0
    verification_latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_status": self.verification_status,
            "is_verified_fact": self.is_verified_fact,
            "verifier_kind": self.verifier_kind,
            "reason": self.reason,
            "verified_answer": self.verified_answer,
            "independent_claim": self.independent_claim,
            "confidence": round(self.confidence, 4),
            "source_frame_id": self.source_frame_id,
            "pts_us": self.pts_us,
            "roi": self.roi,
            "segment_id": self.segment_id,
            "verification_latency_ms": round(self.verification_latency_ms, 2),
            "metadata": self.metadata,
        }


def extract_substantive_tokens(text: str) -> list[str]:
    """Extract semantic, alphanumeric entity tokens while stripping formatting tags and boilerplate."""
    cleaned = re.sub(r"#?F(?:rame)?\s*#?\d+(\s*\d+\.\d+s)?", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:кадр[ае]|frame)\s*#?\d+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\d+\.\d+s", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    tokens = re.findall(r"[a-zA-Zа-яА-Я0-9_-]+", cleaned.lower())
    return [t for t in tokens if t not in GENERIC_STOPWORDS and len(t) >= 2]


class PersistentWindowsOcrPipe:
    """Fast, persistent in-memory WinRT OCR pipe over PowerShell stdio."""

    _PS_CODE = r'''
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod })[0]
function Await($op, $type) {
    $m = $asTask.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.GetAwaiter().GetResult()
}
$engRu = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('ru')))
$engEn = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('en-US')))
Write-Output 'READY'
while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ($line -eq 'QUIT') { break }
    try {
        $bytes = [Convert]::FromBase64String($line)
        $ras = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $dw = New-Object Windows.Storage.Streams.DataWriter($ras.GetOutputStreamAt(0))
        $dw.WriteBytes($bytes)
        $null = Await ($dw.StoreAsync()) ([uint32])
        $ras.Seek(0)
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $sbmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $lines = @()
        if ($null -ne $engRu) {
            $r = Await ($engRu.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
            foreach ($l in $r.Lines) {
                $lines += $l.Text
            }
        }
        if ($null -ne $engEn) {
            $r2 = Await ($engEn.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
            foreach ($l in $r2.Lines) {
                $lines += $l.Text
            }
        }
        $out = @{ ok = $true; lines = $lines } | ConvertTo-Json -Compress
        Write-Output $out
    } catch {
        Write-Output (@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress)
    }
}
'''

    def __init__(self, timeout_s: float = 10.0) -> None:
        self.timeout_s = timeout_s
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._ready = False

    def _ensure_started(self) -> bool:
        if os.name != "nt":
            return False
        if self._proc is not None and self._proc.poll() is None and self._ready:
            return True
        with self._lock:
            try:
                self._proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", self._PS_CODE],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    creationflags=_CREATE_NO_WINDOW,
                )
                ready = self._proc.stdout.readline().strip() if self._proc.stdout else ""
                self._ready = (ready == "READY")
                return self._ready
            except Exception:
                self._proc = None
                self._ready = False
                return False

    def recognize(self, image: Image.Image) -> list[str]:
        """Run OCR on Pillow image. Returns list of recognized text lines."""
        if not self._ensure_started():
            # Fallback to standalone WindowsOcr if persistent pipe cannot be created
            from .windows_ocr import WindowsOcr
            fb = WindowsOcr(timeout_s=self.timeout_s)
            items = fb(image)
            return [it["text"] for it in items]

        with self._lock:
            try:
                buf = io.BytesIO()
                image.convert("RGB").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                assert self._proc is not None and self._proc.stdin and self._proc.stdout
                self._proc.stdin.write(b64 + "\n")
                self._proc.stdin.flush()
                resp_line = self._proc.stdout.readline().strip()
                if not resp_line:
                    return []
                data = json.loads(resp_line)
                if isinstance(data, dict) and data.get("ok"):
                    raw_lines = data.get("lines") or []
                    if isinstance(raw_lines, str):
                        raw_lines = [raw_lines]
                    return [str(l).strip() for l in raw_lines if str(l).strip()]
                return []
            except Exception:
                return []

    def close(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    if self._proc.stdin:
                        self._proc.stdin.write("QUIT\n")
                        self._proc.stdin.flush()
                    self._proc.terminate()
                except Exception:
                    pass
                self._proc = None
                self._ready = False


class TemporalEvidenceVerifier:
    """Independent deterministic verifier for retrospective video observations (AC-06/AC-07)."""

    def __init__(
        self,
        ocr_engine: Callable[[Image.Image], list[str]] | None = None,
        use_persistent_ocr: bool = True,
    ) -> None:
        self._custom_ocr = ocr_engine
        self._persistent_ocr = PersistentWindowsOcrPipe() if (use_persistent_ocr and ocr_engine is None) else None

    def _run_ocr(self, image: Image.Image) -> list[str]:
        if self._custom_ocr is not None:
            return self._custom_ocr(image)
        if self._persistent_ocr is not None:
            return self._persistent_ocr.recognize(image)
        from .windows_ocr import WindowsOcr
        fb = WindowsOcr()
        return [it["text"] for it in fb(image)]

    def verify(
        self,
        evidence: Any,
        candidate_frames: Sequence[tuple[int, float, Image.Image | np.ndarray]] | None = None,
        roi: Sequence[int] | None = None,
        category: str = "general",
    ) -> VerificationResult:
        """Independently verify retrospective evidence against raw sensory sources.

        Args:
            evidence: RetrospectiveEvidence instance from inspect_segment().
            candidate_frames: Decoded frames (frame_id, pts_ms, image) from the inspected window.
            roi: Optional explicit region-of-interest [x, y, w, h].
            category: Domain event category ("chat", "damage_num", "pan_glyph", "loot_drop", etc.).

        Returns:
            VerificationResult detailing whether claim is VERIFIED_FACT, UNVERIFIED, CONTRADICTED,
            or SOURCE_UNAVAILABLE.
        """
        t0 = time.perf_counter()

        # 1. Source Availability Gate
        obs_status = getattr(evidence, "observation_status", str(getattr(evidence, "status", "")))
        missing_count = evidence.metadata.get("missing_frames_count", 0) if hasattr(evidence, "metadata") else 0

        if obs_status == "archive_gap_unavailable" or (missing_count > 0 and not candidate_frames):
            dt_ms = (time.perf_counter() - t0) * 1000.0
            return VerificationResult(
                verification_status=SOURCE_UNAVAILABLE,
                is_verified_fact=False,
                verifier_kind="source_gap_detector",
                reason="Video source frames are unavailable, missing, or dropped by encoder",
                verified_answer=evidence.answer,
                independent_claim="",
                confidence=0.0,
                source_frame_id=getattr(evidence, "best_frame_id", -1),
                pts_us=getattr(evidence, "best_pts_us", -1),
                roi=list(roi) if roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

        # 2. Absence / Negative Evidence Handling
        if obs_status == "not_found_in_sample":
            dt_ms = (time.perf_counter() - t0) * 1000.0
            return VerificationResult(
                verification_status=UNVERIFIED,
                is_verified_fact=False,
                verifier_kind="absence_coverage_evaluator",
                reason="Object not found in sampled frames; physical absence across interval unproven",
                verified_answer=evidence.answer,
                independent_claim="not_found_in_sample",
                confidence=evidence.confidence,
                source_frame_id=-1,
                pts_us=-1,
                roi=list(roi) if roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

        if obs_status == "observed_absent":
            dt_ms = (time.perf_counter() - t0) * 1000.0
            is_confirmed = bool(getattr(evidence, "absence_confirmed", False))
            return VerificationResult(
                verification_status=VERIFIED_FACT if is_confirmed else UNVERIFIED,
                is_verified_fact=is_confirmed,
                verifier_kind="dense_coverage_evaluator",
                reason="Absence definitively confirmed via dense gapless inspection" if is_confirmed else "Coverage gaps present",
                verified_answer=evidence.answer,
                independent_claim="observed_absent",
                confidence=0.95 if is_confirmed else 0.50,
                source_frame_id=-1,
                pts_us=-1,
                roi=list(roi) if roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

        if obs_status == "observed_unreadable":
            dt_ms = (time.perf_counter() - t0) * 1000.0
            return VerificationResult(
                verification_status=UNVERIFIED,
                is_verified_fact=False,
                verifier_kind="physical_quality_filter",
                reason=f"Target unreadable: {getattr(evidence, 'negative_reason', 'degraded_quality')}",
                verified_answer=evidence.answer,
                independent_claim="observed_unreadable",
                confidence=evidence.confidence,
                source_frame_id=getattr(evidence, "best_frame_id", -1),
                pts_us=getattr(evidence, "best_pts_us", -1),
                roi=list(roi) if roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

        # 3. Positive Observation Verification (OBSERVED_READABLE)
        target_roi = roi or getattr(evidence, "best_roi", None)
        best_fid = getattr(evidence, "best_frame_id", -1)

        # Locate candidate image
        target_img: Image.Image | None = None
        target_pts = getattr(evidence, "best_pts_us", -1)

        if candidate_frames:
            # First attempt: find matching frame ID
            for item in candidate_frames:
                f_idx, pts, frame_obj = item[0], item[1], item[2]
                if f_idx == best_fid:
                    target_img = frame_obj if isinstance(frame_obj, Image.Image) else Image.fromarray(frame_obj)
                    target_pts = int(pts * 1000)
                    break
            # Second attempt: pick middle candidate
            if target_img is None and len(candidate_frames) > 0:
                mid_item = candidate_frames[len(candidate_frames) // 2]
                best_fid = mid_item[0]
                target_pts = int(mid_item[1] * 1000)
                frame_obj = mid_item[2]
                target_img = frame_obj if isinstance(frame_obj, Image.Image) else Image.fromarray(frame_obj)

        if target_img is None:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            return VerificationResult(
                verification_status=SOURCE_UNAVAILABLE,
                is_verified_fact=False,
                verifier_kind="frame_fetcher",
                reason="Source frame could not be retrieved from candidates for verification",
                verified_answer=evidence.answer,
                independent_claim="",
                confidence=0.0,
                source_frame_id=best_fid,
                pts_us=target_pts,
                roi=list(target_roi) if target_roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

        # 4. Prepare ROI crop with adaptive vertical/horizontal padding and 2x upscale
        w, h = target_img.size
        if target_roi and len(target_roi) == 4:
            rx, ry, rw, rh = target_roi
            pad_x = 15
            pad_y_top = 30 if category == "damage_num" else 15
            pad_y_bot = 15
            x1 = max(0, rx - pad_x)
            y1 = max(0, ry - pad_y_top)
            x2 = min(w, rx + rw + pad_x)
            y2 = min(h, ry + rh + pad_y_bot)
            crop = target_img.crop((x1, y1, x2, y2))
        else:
            crop = target_img

        # 2x upscale for optimal OCR feature recognition
        crop_2x = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BILINEAR)

        # 5. Execute Independent OCR
        ocr_lines = self._run_ocr(crop_2x)
        ocr_text = " ".join(ocr_lines).strip()
        ocr_tokens = extract_substantive_tokens(ocr_text)

        model_ans = evidence.answer
        model_tokens = extract_substantive_tokens(model_ans)

        # 6. Strict Epistemic Evaluation
        if not model_tokens:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            return VerificationResult(
                verification_status=UNVERIFIED,
                is_verified_fact=False,
                verifier_kind="independent_ocr",
                reason="Model output contains no substantive entity tokens to verify",
                verified_answer=model_ans,
                independent_claim=ocr_text,
                confidence=0.50,
                source_frame_id=best_fid,
                pts_us=target_pts,
                roi=list(target_roi) if target_roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

        if not ocr_tokens:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            # Absence of independent corroboration strictly denies fact elevation (AC-06)
            return VerificationResult(
                verification_status=UNVERIFIED,
                is_verified_fact=False,
                verifier_kind="independent_ocr",
                reason="Independent OCR did not detect verifiable text; unconfirmed model hypothesis",
                verified_answer=model_ans,
                independent_claim="",
                confidence=0.50,
                source_frame_id=best_fid,
                pts_us=target_pts,
                roi=list(target_roi) if target_roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

        # Compute token overlap and substring/prefix matches
        matching_tokens: list[str] = []
        for mt in model_tokens:
            for ot in ocr_tokens:
                if mt == ot:
                    matching_tokens.append(mt)
                    break
                # Code / alphanumeric prefix/substring match (e.g. SIGIL-ALPH vs SIGIL-ALPHA)
                elif len(mt) >= 4 and len(ot) >= 4 and (mt in ot or ot in mt):
                    matching_tokens.append(mt)
                    break

        vlm_overlap_ratio = len(matching_tokens) / max(1, len(model_tokens))

        dt_ms = (time.perf_counter() - t0) * 1000.0

        # Substantive match criteria:
        # Either at least 40% of model entities match, or 2+ substantive tokens match,
        # or at least one long unique identifier (>= 6 chars) matches.
        is_match = matching_tokens and (
            vlm_overlap_ratio >= 0.40
            or len(matching_tokens) >= 2
            or any(len(t) >= 6 for t in matching_tokens)
        )

        if is_match:
            # Independent OCR corroborates model claim!
            verified_ans = model_ans
            if ocr_text and ocr_text not in verified_ans:
                verified_ans = f"{model_ans} [Verified: {ocr_text}]"
            return VerificationResult(
                verification_status=VERIFIED_FACT,
                is_verified_fact=True,
                verifier_kind="independent_ocr",
                reason=f"Independent OCR corroborated entity claim: {matching_tokens}",
                verified_answer=verified_ans,
                independent_claim=ocr_text,
                confidence=min(0.99, max(0.85, 0.80 + 0.05 * len(matching_tokens))),
                source_frame_id=best_fid,
                pts_us=target_pts,
                roi=list(target_roi) if target_roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
                metadata={"matched_tokens": matching_tokens, "ocr_lines": ocr_lines},
            )
        elif ocr_tokens and not matching_tokens:
            # Independent OCR detected clear conflicting text!
            return VerificationResult(
                verification_status=CONTRADICTED,
                is_verified_fact=False,
                verifier_kind="independent_ocr",
                reason=f"Independent OCR contradicts model claim (ocr={ocr_tokens[:3]}, model={model_tokens[:3]})",
                verified_answer=model_ans,
                independent_claim=ocr_text,
                confidence=0.88,
                source_frame_id=best_fid,
                pts_us=target_pts,
                roi=list(target_roi) if target_roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
                metadata={"ocr_lines": ocr_lines},
            )
        else:
            return VerificationResult(
                verification_status=UNVERIFIED,
                is_verified_fact=False,
                verifier_kind="independent_ocr",
                reason="Independent signals insufficient to definitively verify or contradict claim",
                verified_answer=model_ans,
                independent_claim=ocr_text,
                confidence=0.55,
                source_frame_id=best_fid,
                pts_us=target_pts,
                roi=list(target_roi) if target_roi is not None else None,
                segment_id=getattr(evidence, "segment_id", 0),
                verification_latency_ms=dt_ms,
            )

    def close(self) -> None:
        """Release any persistent background resources."""
        if self._persistent_ocr is not None:
            self._persistent_ocr.close()
