"""JAWL Temporal Evidence Index v1 (Round 11, Step 1).

Compact, fault-tolerant binary sidecar index format for retrospective perception.
Maintains continuous time-indexed perceptual telemetry synchronized with raw A/V
recordings without blocking the capture pipeline.

Design Invariants:
1. Non-blocking: Capture pipeline never blocks on indexing. If indexer queue
   fills, frames are dropped gracefully with FLAG_METADATA_DROPPED.
2. Unified Microsecond Timeline: pts_us (uint64) is monotonic across visual
   frames, WASAPI audio, SceneState transitions, and dialogue turns.
3. Fault Recovery: Segmented files (e.g. 5-10s chunks) with magic header,
   per-frame CRC, and clean recovery from abrupt power loss / process crashes.
4. Compact Budget: 256 bytes fixed record size (~55.3 MB/hour @ 60 FPS), zero heavy
   tensor operations, zero extra VRAM, perfectly cache-line aligned.

Format specification (v1):
  Segment Header (32 bytes):
    magic (4B): b"JTE1"
    version (2B): uint16 = 1
    grid_h (1B): uint8 = 21
    grid_w (1B): uint8 = 30
    segment_id (4B): uint32
    start_pts_us (8B): uint64
    fps_hint (4B): float32
    reserved (8B): uint64 = 0

  Frame Record (256 bytes fixed, 4/8-byte aligned):
    -- Section 1: Perceptual Header (32 bytes) --
    frame_id (4B): uint32
    segment_id (4B): uint32
    pts_us (8B): uint64
    scene_version (2B): uint16
    quality_flags (2B): uint16
    global_motion_score (4B): float32
    sharpness_score (4B): float32
    edge_text_score (4B): float32

    -- Section 2: Spatial Bitmasks (160 bytes) --
    local_change_mask (80B): 79B (630 bits for 21x30) + 1B pad
    ui_likelihood_mask (80B): 79B (630 bits for 21x30) + 1B pad

    -- Section 3: High-Priority Candidate ROIs (48 bytes) --
    roi_count (4B): uint32 (0..2)
    roi_0 (20B): x(4B), y(4B), w(4B), h(4B) [uint32], conf(4B) [float32]
    roi_1 (20B): x(4B), y(4B), w(4B), h(4B) [uint32], conf(4B) [float32]
    roi_pad (4B): uint32 = 0

    -- Section 4: Tail & Integrity (16 bytes) --
    reserved (12B): bytes
    crc32 (4B): uint32 over first 252 bytes
"""

from __future__ import annotations

import os
import queue
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Generator, Iterable, Sequence

import numpy as np

MAGIC_V1 = b"JTE1"
VERSION_V1 = 1
GRID_H_DEFAULT = 21
GRID_W_DEFAULT = 30
TOTAL_TILES_DEFAULT = GRID_H_DEFAULT * GRID_W_DEFAULT  # 630
MASK_BYTES_DEFAULT = (TOTAL_TILES_DEFAULT + 7) // 8    # 79 bytes
MASK_SECTION_SIZE = 80                                # 79 bytes mask + 1 pad

# Quality Flags
FLAG_NONE = 0x0000
FLAG_METADATA_DROPPED = 0x0001
FLAG_OVEREXPOSED = 0x0002
FLAG_UNDEREXPOSED = 0x0004
FLAG_HIGH_MOTION_BLUR = 0x0008
FLAG_OCR_CANDIDATE = 0x0010
FLAG_UI_TARGET = 0x0020
FLAG_CORRUPTED_FRAME = 0x0040

HEADER_STRUCT = struct.Struct("<4sHBBIQfQ")  # 32 bytes (4+2+1+1 + 4 + 8 + 4 + 8 = 32)
RECORD_HEADER_STRUCT = struct.Struct("<IIQHHfff")  # 32 bytes (4+4+8+2+2 + 4+4+4 = 32)
ROI_STRUCT = struct.Struct("<4If")  # 20 bytes (4*4 + 4)
RECORD_FIXED_SIZE = 256


@dataclass
class IndexFrameRecord:
    """Telemetry record for a single visual frame in the sidecar index."""
    frame_id: int
    segment_id: int
    pts_us: int
    scene_version: int = 0
    quality_flags: int = FLAG_NONE
    global_motion_score: float = 0.0
    sharpness_score: float = 0.0
    edge_text_score: float = 0.0
    local_change_mask: bytes = b"\x00" * MASK_BYTES_DEFAULT
    ui_likelihood_mask: bytes = b"\x00" * MASK_BYTES_DEFAULT
    candidate_rois: list[tuple[int, int, int, int, float]] = field(default_factory=list)  # (x, y, w, h, conf)

    @classmethod
    def from_masks(
        cls,
        frame_id: int,
        segment_id: int,
        pts_us: int,
        scene_version: int = 0,
        quality_flags: int = FLAG_NONE,
        global_motion: float = 0.0,
        sharpness: float = 0.0,
        edge_text: float = 0.0,
        change_mask_bool: np.ndarray | None = None,
        ui_mask_bool: np.ndarray | None = None,
        candidate_rois: list[tuple[int, int, int, int, float]] | None = None,
    ) -> "IndexFrameRecord":
        c_bytes = cls._pack_bool_mask(change_mask_bool) if change_mask_bool is not None else b"\x00" * MASK_BYTES_DEFAULT
        u_bytes = cls._pack_bool_mask(ui_mask_bool) if ui_mask_bool is not None else b"\x00" * MASK_BYTES_DEFAULT
        return cls(
            frame_id=frame_id,
            segment_id=segment_id,
            pts_us=pts_us,
            scene_version=scene_version,
            quality_flags=quality_flags,
            global_motion_score=global_motion,
            sharpness_score=sharpness,
            edge_text_score=edge_text,
            local_change_mask=c_bytes,
            ui_likelihood_mask=u_bytes,
            candidate_rois=candidate_rois or [],
        )

    @staticmethod
    def _pack_bool_mask(arr: np.ndarray) -> bytes:
        flat = arr.flatten().astype(bool)
        pad_len = MASK_BYTES_DEFAULT * 8 - len(flat)
        if pad_len > 0:
            flat = np.pad(flat, (0, pad_len), constant_values=False)
        return np.packbits(flat).tobytes()[:MASK_BYTES_DEFAULT]

    def unpack_change_mask(self, shape: tuple[int, int] = (GRID_H_DEFAULT, GRID_W_DEFAULT)) -> np.ndarray:
        unpacked = np.unpackbits(np.frombuffer(self.local_change_mask, dtype=np.uint8))
        total = shape[0] * shape[1]
        return unpacked[:total].reshape(shape).astype(bool)

    def unpack_ui_mask(self, shape: tuple[int, int] = (GRID_H_DEFAULT, GRID_W_DEFAULT)) -> np.ndarray:
        unpacked = np.unpackbits(np.frombuffer(self.ui_likelihood_mask, dtype=np.uint8))
        total = shape[0] * shape[1]
        return unpacked[:total].reshape(shape).astype(bool)

    def pack(self) -> bytes:
        # Section 1: Header (32 bytes)
        sec1 = RECORD_HEADER_STRUCT.pack(
            self.frame_id,
            self.segment_id,
            self.pts_us,
            self.scene_version,
            self.quality_flags,
            self.global_motion_score,
            self.sharpness_score,
            self.edge_text_score,
        )

        # Section 2: Bitmasks (80 + 80 = 160 bytes)
        c_mask = (self.local_change_mask[:MASK_BYTES_DEFAULT]).ljust(MASK_SECTION_SIZE, b"\x00")
        u_mask = (self.ui_likelihood_mask[:MASK_BYTES_DEFAULT]).ljust(MASK_SECTION_SIZE, b"\x00")
        sec2 = c_mask + u_mask

        # Section 3: ROIs (48 bytes)
        rois = self.candidate_rois[:2]
        r_count = len(rois)
        sec3_ba = bytearray(struct.pack("<I", r_count))
        for i in range(2):
            if i < r_count:
                rx, ry, rw, rh, rc = rois[i]
                sec3_ba.extend(ROI_STRUCT.pack(int(rx), int(ry), int(rw), int(rh), float(rc)))
            else:
                sec3_ba.extend(b"\x00" * 20)
        sec3_ba.extend(b"\x00" * 4)  # pad to 48 bytes
        sec3 = bytes(sec3_ba)

        # Section 4: Reserved (12 bytes)
        sec4_res = b"\x00" * 12

        payload = sec1 + sec2 + sec3 + sec4_res
        assert len(payload) == 252, f"Payload size mismatch: {len(payload)} != 252"

        crc = zlib.crc32(payload) & 0xFFFFFFFF
        return payload + struct.pack("<I", crc)

    @classmethod
    def unpack(cls, raw: bytes) -> "IndexFrameRecord":
        if len(raw) < RECORD_FIXED_SIZE:
            raise ValueError(f"Raw buffer too small for record: {len(raw)} < {RECORD_FIXED_SIZE}")

        payload = raw[:RECORD_FIXED_SIZE - 4]
        expected_crc = struct.unpack("<I", raw[RECORD_FIXED_SIZE - 4:RECORD_FIXED_SIZE])[0]
        actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"CRC mismatch in record: {expected_crc:#010x} != {actual_crc:#010x}")

        (
            frame_id,
            segment_id,
            pts_us,
            scene_version,
            quality_flags,
            global_motion,
            sharpness,
            edge_text,
        ) = RECORD_HEADER_STRUCT.unpack(payload[:RECORD_HEADER_STRUCT.size])

        offset = RECORD_HEADER_STRUCT.size
        c_mask = payload[offset:offset + MASK_BYTES_DEFAULT]
        offset += MASK_SECTION_SIZE
        u_mask = payload[offset:offset + MASK_BYTES_DEFAULT]
        offset += MASK_SECTION_SIZE

        r_count = struct.unpack("<I", payload[offset:offset + 4])[0]
        offset += 4
        rois: list[tuple[int, int, int, int, float]] = []
        for _ in range(min(2, int(r_count))):
            rx, ry, rw, rh, rc = ROI_STRUCT.unpack(payload[offset:offset + 20])
            offset += 20
            rois.append((rx, ry, rw, rh, float(rc)))

        return cls(
            frame_id=frame_id,
            segment_id=segment_id,
            pts_us=pts_us,
            scene_version=scene_version,
            quality_flags=quality_flags,
            global_motion_score=float(global_motion),
            sharpness_score=float(sharpness),
            edge_text_score=float(edge_text),
            local_change_mask=c_mask,
            ui_likelihood_mask=u_mask,
            candidate_rois=rois,
        )


class TemporalEvidenceIndexWriter:
    """Writes a stream of IndexFrameRecord entries into a segment file."""

    def __init__(
        self,
        filepath: str | Path,
        segment_id: int,
        start_pts_us: int,
        fps_hint: float = 60.0,
        grid_h: int = GRID_H_DEFAULT,
        grid_w: int = GRID_W_DEFAULT,
    ) -> None:
        self.filepath = Path(filepath).resolve()
        self.segment_id = segment_id
        self.start_pts_us = start_pts_us
        self.fps_hint = fps_hint
        self.grid_h = grid_h
        self.grid_w = grid_w
        self._fp: BinaryIO | None = None
        self._record_count = 0
        self._lock = threading.Lock()

    def open(self) -> "TemporalEvidenceIndexWriter":
        with self._lock:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            fp = open(self.filepath, "wb")
            try:
                header = HEADER_STRUCT.pack(
                    MAGIC_V1,
                    VERSION_V1,
                    self.grid_h,
                    self.grid_w,
                    self.segment_id,
                    self.start_pts_us,
                    self.fps_hint,
                    0,  # reserved
                )
                fp.write(header)
                fp.flush()
                self._fp = fp
            except Exception:
                fp.close()
                raise
        return self

    def write_record(self, record: IndexFrameRecord) -> None:
        with self._lock:
            if self._fp is None:
                raise RuntimeError("Writer is not open")
            data = record.pack()
            self._fp.write(data)
            self._record_count += 1

    def flush(self) -> None:
        with self._lock:
            if self._fp:
                self._fp.flush()

    def close(self) -> int:
        with self._lock:
            if self._fp is not None:
                try:
                    self._fp.flush()
                finally:
                    self._fp.close()
                    self._fp = None
            return self._record_count

    def __enter__(self) -> "TemporalEvidenceIndexWriter":
        return self.open()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class TemporalEvidenceIndexReader:
    """Reads and queries an index segment with automatic crash recovery."""

    def __init__(self, filepath: str | Path) -> None:
        self.filepath = Path(filepath).resolve()
        if not self.filepath.is_file():
            raise FileNotFoundError(f"Index file not found: {self.filepath}")

        self.segment_id = 0
        self.start_pts_us = 0
        self.fps_hint = 60.0
        self.grid_h = GRID_H_DEFAULT
        self.grid_w = GRID_W_DEFAULT
        self.corrupted_records = 0
        self.recovered_records = 0
        self._read_header()

    def _read_header(self) -> None:
        with open(self.filepath, "rb") as fp:
            raw_header = fp.read(HEADER_STRUCT.size)
            if len(raw_header) < HEADER_STRUCT.size:
                raise ValueError("Corrupted index header: file too small")
            (
                magic,
                version,
                gh,
                gw,
                seg_id,
                start_pts,
                fps,
                _,
            ) = HEADER_STRUCT.unpack(raw_header)

            if magic != MAGIC_V1:
                raise ValueError(f"Invalid magic: {magic} != {MAGIC_V1}")
            if version != VERSION_V1:
                raise ValueError(f"Unsupported index version: {version}")

            self.grid_h = gh
            self.grid_w = gw
            self.segment_id = seg_id
            self.start_pts_us = start_pts
            self.fps_hint = fps

    def read_all_records(self) -> list[IndexFrameRecord]:
        """Read all valid records in the file with CRC validation and crash tolerance."""
        records: list[IndexFrameRecord] = []
        with open(self.filepath, "rb") as fp:
            fp.seek(HEADER_STRUCT.size)
            while True:
                chunk = fp.read(RECORD_FIXED_SIZE)
                if len(chunk) < RECORD_FIXED_SIZE:
                    if len(chunk) > 0:
                        # Partial trailing write from crash
                        self.corrupted_records += 1
                    break
                try:
                    rec = IndexFrameRecord.unpack(chunk)
                    records.append(rec)
                    self.recovered_records += 1
                except ValueError:
                    self.corrupted_records += 1
                    break
        return records

    def query_interval(
        self, start_pts_us: int, end_pts_us: int
    ) -> list[IndexFrameRecord]:
        """Extract records whose pts_us lies within [start_pts_us, end_pts_us]."""
        matches = []
        for rec in self.read_all_records():
            if start_pts_us <= rec.pts_us <= end_pts_us:
                matches.append(rec)
        return matches


class NonBlockingAsyncIndexer:
    """Non-blocking sidecar indexing worker.

    Consumes frame features from a bounded queue. If queue overflows, drops metadata
    gracefully to guarantee zero latency overhead on live video recording.
    """

    def __init__(
        self,
        writer: TemporalEvidenceIndexWriter,
        max_queue_size: int = 120,
    ) -> None:
        self.writer = writer
        self.queue: queue.Queue[IndexFrameRecord | None] = queue.Queue(maxsize=max_queue_size)
        self.dropped_frames = 0
        self.processed_frames = 0
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

    def start(self) -> None:
        self.writer.open()
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run, name="AsyncSidecarIndexer", daemon=True
        )
        self._worker_thread.start()

    def submit_frame(self, record: IndexFrameRecord) -> bool:
        """Submit a frame record without blocking.

        Returns True if accepted; False if dropped due to queue congestion.
        """
        try:
            self.queue.put_nowait(record)
            return True
        except queue.Full:
            self.dropped_frames += 1
            return False

    def _run(self) -> None:
        while True:
            try:
                rec = self.queue.get(timeout=0.05)
                if rec is None:
                    self.queue.task_done()
                    break
                if self.dropped_frames > 0:
                    rec.quality_flags |= FLAG_METADATA_DROPPED
                self.writer.write_record(rec)
                self.processed_frames += 1
                self.queue.task_done()
            except queue.Empty:
                if self._stop_event.is_set():
                    break

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop_event.set()
        try:
            self.queue.put(None, timeout=0.5)
        except queue.Full:
            pass
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout_s)
        self.writer.close()


def read_legacy_jte1_as_jti1(filepath: str | Path) -> list[Any]:
    """Read a legacy .jte1 file and convert its records to canonical JTI1 IndexFrameRecord instances.

    Ensures 100% backward compatibility for archived .jte1 legacy files while enforcing
    JTI1 as the single active canonical format for all new writes.
    """
    from .temporal_index import IndexFrameRecord as JTI1Record, FLAG_VALID
    reader = TemporalEvidenceIndexReader(filepath)
    legacy_records = reader.read_all_records()
    canonical_records = []
    for r in legacy_records:
        rec = JTI1Record(
            capture_qpc_us=r.pts_us,
            video_pts_us=r.pts_us,
            capture_frame_id=r.frame_id,
            segment_sample_idx=r.frame_id,
            scene_version=r.scene_version,
            dirty_tile_count=0,
            quality_flags=r.quality_flags | FLAG_VALID,
            global_motion_score=r.global_motion_score,
            sharpness_score=r.sharpness_score,
            edge_text_score=r.edge_text_score,
            local_change_mask=r.local_change_mask,
            ui_static_mask=r.ui_likelihood_mask,
        )
        canonical_records.append(rec)
    return canonical_records

