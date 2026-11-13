"""JAWL Temporal Evidence Index v1 (.jti sidecar format).

Fixed 256-byte append-only binary frame records with 64-byte header.
Synchronized monotonic timecodes (capture_qpc_us, video_pts_us, audio_start_qpc_us).
Multi-scale perceptual telemetry (21x30 spatial grid, micro-grid ROIs, HUD static mask).
Full crash-recovery with non-zero seeded CRC32 (seed=0xA5A5A5A5) protecting against
truncated writes, null-byte padding, and bitflips.

Format specification (v1):
  Header (64 bytes, Little-Endian):
    magic: char[4] = b"JTI1"
    schema_version: uint16 = 1
    header_flags: uint16 (0x01 = CLEAN_CLOSED)
    segment_id: uint32
    source_width: uint16
    source_height: uint16
    grid_rows: uint8 = 21
    grid_cols: uint8 = 30
    record_size: uint16 = 256
    qpc_freq_hz: uint64
    first_capture_qpc_us: int64
    audio_start_qpc_us: int64
    reserved: uint8[16]
    header_crc32c: uint32 (CRC32 over bytes 0..59, seed=0xA5A5A5A5)

  Frame Record (256 bytes, Little-Endian):
    0..7:   capture_qpc_us (int64)
    8..15:  video_pts_us (int64, -1 if dropped by encoder)
    16..19: capture_frame_id (uint32)
    20..23: segment_sample_idx (int32, -1 if encoder dropped)
    24..25: scene_version (uint16)
    26..27: dirty_tile_count (uint16, 0..630)
    28..31: quality_flags (uint32: 0x01=VALID, 0x02=FEATURES_SKIPPED, 0x04=OVEREXPOSED, 0x08=CAPTURE_GAP, 0x10=ENCODER_DROPPED)
    32..47: scalar_scores (float32 x 4: global_motion_score, sharpness_score, edge_text_score, mean_luma)
    48..127: local_change_mask (uint8[80]: 630 bits dirty tiles + 10 bits padding)
    128..207: ui_static_mask (uint8[80]: 630 bits binary static HUD mask + 10 bits padding)
    208..247: candidate_rois (4 x ROI[10]: x_px[u16], y_px[u16], w_px[u16], h_px[u16], score_q8[u8], kind[u8])
    248..251: audio_telemetry (uint16 x 2: audio_rms_q16, vad_state_flags)
    252..255: record_crc32c (uint32 over bytes 0..251, seed=0xA5A5A5A5)
"""

from __future__ import annotations

import os
import struct
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Generator, Iterable, List, Sequence, Tuple

import numpy as np

# Magic and constants
MAGIC_V1 = b"JTI1"
VERSION_V1 = 1
RECORD_SIZE_V1 = 256
HEADER_SIZE_V1 = 64
CRC32_SEED = 0xA5A5A5A5

GRID_ROWS_DEFAULT = 21
GRID_COLS_DEFAULT = 30
TOTAL_TILES_DEFAULT = GRID_ROWS_DEFAULT * GRID_COLS_DEFAULT  # 630
MASK_BYTES_DEFAULT = (TOTAL_TILES_DEFAULT + 7) // 8         # 79 bytes
MASK_SECTION_SIZE = 80                                     # 79 bytes + 1 padding byte

# Header Flags
FLAG_HEADER_CLEAN_CLOSED = 0x0001

# Quality Flags
FLAG_VALID = 0x0001
FLAG_FEATURES_SKIPPED = 0x0002
FLAG_OVEREXPOSED = 0x0004
FLAG_CAPTURE_GAP = 0x0008
FLAG_ENCODER_DROPPED = 0x0010
FLAG_SOURCE_FRAME_MISSING = 0x0020

# ROI Kinds
ROI_KIND_EMPTY = 0
ROI_KIND_TEXT_LIKE = 1
ROI_KIND_OBJECT_DELTA = 2

# Struct formats (all Little-Endian)
# Header: magic(4s), version(H), flags(H), seg_id(I), src_w(H), src_h(H), rows(B), cols(B), rec_sz(H), qpc_freq(Q), first_qpc(q), audio_qpc(q), res(16s)
HEADER_BODY_FMT = "<4sHHIHHBBHQqq16s"
HEADER_FULL_FMT = HEADER_BODY_FMT + "I"
assert struct.calcsize(HEADER_FULL_FMT) == HEADER_SIZE_V1

# Record: capture_qpc(q), video_pts(q), frame_id(I), seg_idx(i), scene_v(H), dirty_cnt(H), q_flags(I),
# 4 floats (motion, sharp, edge, luma) (4f),
# local_mask(80s), ui_mask(80s),
# 4 ROIs (4 x HHHHBB),
# audio (HH)
RECORD_BODY_FMT = "<qqIiHHIffff80s80sHHHHBBHHHHBBHHHHBBHHHHBBHH"
RECORD_FULL_FMT = RECORD_BODY_FMT + "I"
assert struct.calcsize(RECORD_BODY_FMT) == 252
assert struct.calcsize(RECORD_FULL_FMT) == RECORD_SIZE_V1


@dataclass
class IndexROI:
    """High-priority candidate Region of Interest in source screen pixel coordinates."""
    x_px: int = 0
    y_px: int = 0
    w_px: int = 0
    h_px: int = 0
    score_q8: int = 0
    kind: int = ROI_KIND_EMPTY

    def as_tuple(self) -> Tuple[int, int, int, int, int, int]:
        return (self.x_px, self.y_px, self.w_px, self.h_px, self.score_q8, self.kind)


@dataclass
class IndexSegmentHeader:
    """Header information for a single .jti evidence index segment."""
    magic: bytes = MAGIC_V1
    schema_version: int = VERSION_V1
    header_flags: int = 0
    segment_id: int = 0
    source_width: int = 1280
    source_height: int = 720
    grid_rows: int = GRID_ROWS_DEFAULT
    grid_cols: int = GRID_COLS_DEFAULT
    record_size: int = RECORD_SIZE_V1
    qpc_freq_hz: int = 10_000_000
    first_capture_qpc_us: int = 0
    audio_start_qpc_us: int = 0
    reserved: bytes = b"\x00" * 16

    @property
    def is_clean_closed(self) -> bool:
        return bool(self.header_flags & FLAG_HEADER_CLEAN_CLOSED)

    def pack(self) -> bytes:
        body = struct.pack(
            HEADER_BODY_FMT,
            self.magic,
            self.schema_version,
            self.header_flags,
            self.segment_id,
            self.source_width,
            self.source_height,
            self.grid_rows,
            self.grid_cols,
            self.record_size,
            self.qpc_freq_hz,
            self.first_capture_qpc_us,
            self.audio_start_qpc_us,
            self.reserved,
        )
        crc = zlib.crc32(body, CRC32_SEED) & 0xFFFFFFFF
        return body + struct.pack("<I", crc)

    @classmethod
    def unpack(cls, data: bytes) -> IndexSegmentHeader:
        if len(data) != HEADER_SIZE_V1:
            raise ValueError(f"Header size must be {HEADER_SIZE_V1} bytes, got {len(data)}")
        body = data[:60]
        expected_crc = struct.unpack("<I", data[60:64])[0]
        computed_crc = zlib.crc32(body, CRC32_SEED) & 0xFFFFFFFF
        if expected_crc != computed_crc:
            raise ValueError(f"Header CRC32 mismatch: expected 0x{expected_crc:08X}, got 0x{computed_crc:08X}")

        (
            magic,
            schema_version,
            header_flags,
            segment_id,
            source_width,
            source_height,
            grid_rows,
            grid_cols,
            record_size,
            qpc_freq_hz,
            first_capture_qpc_us,
            audio_start_qpc_us,
            reserved,
        ) = struct.unpack(HEADER_BODY_FMT, body)

        if magic != MAGIC_V1:
            raise ValueError(f"Invalid magic: {magic}, expected {MAGIC_V1}")
        if schema_version != VERSION_V1:
            raise ValueError(f"Unsupported schema version: {schema_version}")

        return cls(
            magic=magic,
            schema_version=schema_version,
            header_flags=header_flags,
            segment_id=segment_id,
            source_width=source_width,
            source_height=source_height,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            record_size=record_size,
            qpc_freq_hz=qpc_freq_hz,
            first_capture_qpc_us=first_capture_qpc_us,
            audio_start_qpc_us=audio_start_qpc_us,
            reserved=reserved,
        )


@dataclass
class IndexFrameRecord:
    """Fixed 256-byte telemetry record for a single visual frame."""
    capture_qpc_us: int
    video_pts_us: int = -1
    capture_frame_id: int = 0
    segment_sample_idx: int = -1
    scene_version: int = 0
    dirty_tile_count: int = 0
    quality_flags: int = FLAG_VALID
    global_motion_score: float = 0.0
    sharpness_score: float = 0.0
    edge_text_score: float = 0.0
    mean_luma: float = 0.0
    local_change_mask: bytes = b"\x00" * MASK_SECTION_SIZE
    ui_static_mask: bytes = b"\x00" * MASK_SECTION_SIZE
    candidate_rois: List[IndexROI] = field(default_factory=list)
    audio_rms_q16: int = 0
    vad_state_flags: int = 0
    _segment_id: int = field(default=0, repr=False, compare=False)

    @property
    def frame_id(self) -> int:
        return self.capture_frame_id

    @property
    def pts_us(self) -> int:
        return self.video_pts_us if self.video_pts_us >= 0 else self.capture_qpc_us

    @property
    def segment_id(self) -> int:
        return self._segment_id

    @segment_id.setter
    def segment_id(self, val: int) -> None:
        self._segment_id = int(val)

    @property
    def ui_likelihood_mask(self) -> bytes:
        return self.ui_static_mask

    @property
    def global_motion(self) -> float:
        return self.global_motion_score

    @property
    def sharpness(self) -> float:
        return self.sharpness_score

    @property
    def edge_text(self) -> float:
        return self.edge_text_score

    @classmethod
    def from_masks(
        cls,
        frame_id: int = 0,
        segment_id: int = 0,
        pts_us: int = -1,
        scene_version: int = 0,
        quality_flags: int = FLAG_VALID,
        global_motion: float = 0.0,
        sharpness: float = 0.0,
        edge_text: float = 0.0,
        mean_luma: float = 0.0,
        change_mask_bool: np.ndarray | None = None,
        ui_mask_bool: np.ndarray | None = None,
        candidate_rois: list | None = None,
        audio_rms_q16: int = 0,
        vad_state_flags: int = 0,
        capture_qpc_us: int | None = None,
    ) -> "IndexFrameRecord":
        c_bytes = cls.from_bool_mask(change_mask_bool) if change_mask_bool is not None else b"\x00" * MASK_SECTION_SIZE
        u_bytes = cls.from_bool_mask(ui_mask_bool) if ui_mask_bool is not None else b"\x00" * MASK_SECTION_SIZE

        # Convert rois if passed as tuples or IndexROI
        parsed_rois: List[IndexROI] = []
        if candidate_rois:
            for r in candidate_rois:
                if isinstance(r, IndexROI):
                    parsed_rois.append(r)
                elif isinstance(r, (tuple, list)) and len(r) >= 4:
                    rx, ry, rw, rh = int(r[0]), int(r[1]), int(r[2]), int(r[3])
                    score = int(r[4] * 255) if len(r) > 4 and isinstance(r[4], float) else (int(r[4]) if len(r) > 4 else 0)
                    kind = int(r[5]) if len(r) > 5 else ROI_KIND_OBJECT_DELTA
                    parsed_rois.append(IndexROI(rx, ry, rw, rh, score, kind))

        qpc = capture_qpc_us if capture_qpc_us is not None else (pts_us if pts_us >= 0 else int(time.perf_counter() * 1_000_000))
        dirty_cnt = int(np.count_nonzero(change_mask_bool)) if change_mask_bool is not None else 0

        return cls(
            capture_qpc_us=qpc,
            video_pts_us=pts_us,
            capture_frame_id=frame_id,
            segment_sample_idx=frame_id,
            scene_version=scene_version,
            dirty_tile_count=dirty_cnt,
            quality_flags=quality_flags,
            global_motion_score=global_motion,
            sharpness_score=sharpness,
            edge_text_score=edge_text,
            mean_luma=mean_luma,
            local_change_mask=c_bytes,
            ui_static_mask=u_bytes,
            candidate_rois=parsed_rois,
            audio_rms_q16=audio_rms_q16,
            vad_state_flags=vad_state_flags,
            _segment_id=segment_id,
        )

    def unpack_change_mask(self, rows: int = GRID_ROWS_DEFAULT, cols: int = GRID_COLS_DEFAULT) -> np.ndarray:
        return self.unpack_local_change_mask(rows, cols)

    def unpack_ui_mask(self, rows: int = GRID_ROWS_DEFAULT, cols: int = GRID_COLS_DEFAULT) -> np.ndarray:
        return self.unpack_ui_static_mask(rows, cols)

    @classmethod
    def from_bool_mask(cls, bool_arr: np.ndarray) -> bytes:
        """Pack a 21x30 (630 elements) boolean numpy array into an 80-byte bitmask."""
        flat = bool_arr.flatten()
        padded = np.zeros(MASK_SECTION_SIZE * 8, dtype=bool)
        limit = min(len(flat), TOTAL_TILES_DEFAULT)
        padded[:limit] = flat[:limit]
        packed = np.packbits(padded)
        return packed.tobytes()

    def unpack_local_change_mask(self, rows: int = GRID_ROWS_DEFAULT, cols: int = GRID_COLS_DEFAULT) -> np.ndarray:
        """Unpack 80-byte bitmask into (rows, cols) boolean array."""
        unpacked = np.unpackbits(np.frombuffer(self.local_change_mask, dtype=np.uint8))
        return unpacked[: rows * cols].reshape(rows, cols).astype(bool)

    def unpack_ui_static_mask(self, rows: int = GRID_ROWS_DEFAULT, cols: int = GRID_COLS_DEFAULT) -> np.ndarray:
        """Unpack 80-byte bitmask into (rows, cols) boolean array."""
        unpacked = np.unpackbits(np.frombuffer(self.ui_static_mask, dtype=np.uint8))
        return unpacked[: rows * cols].reshape(rows, cols).astype(bool)

    def pack(self) -> bytes:
        # Prepare 4 ROIs
        rois = list(self.candidate_rois)[:4]
        while len(rois) < 4:
            rois.append(IndexROI())

        r0, r1, r2, r3 = rois[0], rois[1], rois[2], rois[3]

        # Ensure masks are 80 bytes
        l_mask = self.local_change_mask[:80].ljust(80, b"\x00")
        u_mask = self.ui_static_mask[:80].ljust(80, b"\x00")

        body = struct.pack(
            RECORD_BODY_FMT,
            self.capture_qpc_us,
            self.video_pts_us,
            self.capture_frame_id,
            self.segment_sample_idx,
            self.scene_version,
            self.dirty_tile_count,
            self.quality_flags,
            self.global_motion_score,
            self.sharpness_score,
            self.edge_text_score,
            self.mean_luma,
            l_mask,
            u_mask,
            r0.x_px, r0.y_px, r0.w_px, r0.h_px, r0.score_q8, r0.kind,
            r1.x_px, r1.y_px, r1.w_px, r1.h_px, r1.score_q8, r1.kind,
            r2.x_px, r2.y_px, r2.w_px, r2.h_px, r2.score_q8, r2.kind,
            r3.x_px, r3.y_px, r3.w_px, r3.h_px, r3.score_q8, r3.kind,
            self.audio_rms_q16,
            self.vad_state_flags,
        )
        crc = zlib.crc32(body, CRC32_SEED) & 0xFFFFFFFF
        return body + struct.pack("<I", crc)

    @classmethod
    def unpack(cls, data: bytes, validate_crc: bool = True) -> IndexFrameRecord:
        if len(data) != RECORD_SIZE_V1:
            raise ValueError(f"Record size must be {RECORD_SIZE_V1} bytes, got {len(data)}")

        if validate_crc:
            body = data[:252]
            expected_crc = struct.unpack("<I", data[252:256])[0]
            computed_crc = zlib.crc32(body, CRC32_SEED) & 0xFFFFFFFF
            if expected_crc != computed_crc:
                raise ValueError(f"Record CRC32 mismatch: expected 0x{expected_crc:08X}, got 0x{computed_crc:08X}")

        values = struct.unpack(RECORD_BODY_FMT, data[:252])
        (
            capture_qpc_us,
            video_pts_us,
            capture_frame_id,
            segment_sample_idx,
            scene_version,
            dirty_tile_count,
            quality_flags,
            global_motion_score,
            sharpness_score,
            edge_text_score,
            mean_luma,
            local_change_mask,
            ui_static_mask,
            r0_x, r0_y, r0_w, r0_h, r0_s, r0_k,
            r1_x, r1_y, r1_w, r1_h, r1_s, r1_k,
            r2_x, r2_y, r2_w, r2_h, r2_s, r2_k,
            r3_x, r3_y, r3_w, r3_h, r3_s, r3_k,
            audio_rms_q16,
            vad_state_flags,
        ) = values

        rois = [
            IndexROI(r0_x, r0_y, r0_w, r0_h, r0_s, r0_k),
            IndexROI(r1_x, r1_y, r1_w, r1_h, r1_s, r1_k),
            IndexROI(r2_x, r2_y, r2_w, r2_h, r2_s, r2_k),
            IndexROI(r3_x, r3_y, r3_w, r3_h, r3_s, r3_k),
        ]
        # Filter out empty ROIs
        active_rois = [r for r in rois if r.kind != ROI_KIND_EMPTY]

        return cls(
            capture_qpc_us=capture_qpc_us,
            video_pts_us=video_pts_us,
            capture_frame_id=capture_frame_id,
            segment_sample_idx=segment_sample_idx,
            scene_version=scene_version,
            dirty_tile_count=dirty_tile_count,
            quality_flags=quality_flags,
            global_motion_score=global_motion_score,
            sharpness_score=sharpness_score,
            edge_text_score=edge_text_score,
            mean_luma=mean_luma,
            local_change_mask=local_change_mask,
            ui_static_mask=ui_static_mask,
            candidate_rois=active_rois,
            audio_rms_q16=audio_rms_q16,
            vad_state_flags=vad_state_flags,
        )


class TemporalIndexWriter:
    """Appends 256-byte frame records to a .jti sidecar file with atomic header updating."""

    def __init__(self, path: Path | str, header: IndexSegmentHeader) -> None:
        self.path = Path(path)
        self.header = header
        self._fp: BinaryIO | None = None
        self._record_count = 0
        self._last_capture_qpc_us = -1
        self._closed = False

    def __enter__(self) -> TemporalIndexWriter:
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.path, "wb+")
        # Write initial header with flags=0 (not clean closed yet)
        self._fp.write(self.header.pack())
        self._fp.flush()

    def write_record(self, record: IndexFrameRecord, flush: bool = False) -> None:
        if self._fp is None or self._closed:
            raise RuntimeError("Cannot write to closed TemporalIndexWriter")

        # Monotonicity check
        if record.capture_qpc_us < self._last_capture_qpc_us:
            # Monotonicity warning: log and clamp or flag CAPTURE_GAP
            record.quality_flags |= FLAG_CAPTURE_GAP

        self._last_capture_qpc_us = record.capture_qpc_us
        self._fp.write(record.pack())
        self._record_count += 1

        if flush:
            self._fp.flush()

    def close(self) -> None:
        if self._fp is None or self._closed:
            return

        # Mark clean closed in header
        self.header.header_flags |= FLAG_HEADER_CLEAN_CLOSED
        try:
            self._fp.seek(0)
            self._fp.write(self.header.pack())
            self._fp.flush()
            os.fsync(self._fp.fileno())
        except Exception:
            pass
        finally:
            self._fp.close()
            self._fp = None
            self._closed = True

    @property
    def record_count(self) -> int:
        return self._record_count


class TemporalIndexReader:
    """Reads and validates .jti sidecar files with robust Crash Recovery.

    Halts on first CRC error or truncated tail, providing clean recovery and truncation.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.header: IndexSegmentHeader | None = None
        self.records: List[IndexFrameRecord] = []
        self.valid_records_count = 0
        self.corrupted_records = 0
        self.is_truncated = False
        self.valid_bytes_offset = 0

    def read_all_records(self, stop_on_error: bool = True) -> List[IndexFrameRecord]:
        """Parse all valid records from the file up to the first crash/corruption point."""
        self.records.clear()
        self.valid_records_count = 0
        self.corrupted_records = 0
        self.is_truncated = False
        self.valid_bytes_offset = 0

        if not self.path.is_file():
            return []

        file_size = self.path.stat().st_size
        if file_size < HEADER_SIZE_V1:
            self.is_truncated = True
            return []

        with open(self.path, "rb") as f:
            header_bytes = f.read(HEADER_SIZE_V1)
            try:
                self.header = IndexSegmentHeader.unpack(header_bytes)
                self.valid_bytes_offset = HEADER_SIZE_V1
            except Exception:
                # Corrupted header
                self.corrupted_records += 1
                return []

            prev_qpc = -1
            while True:
                chunk = f.read(RECORD_SIZE_V1)
                if not chunk:
                    break
                if len(chunk) < RECORD_SIZE_V1:
                    # Truncated partial record at the end (crash recovery)
                    self.is_truncated = True
                    break

                try:
                    record = IndexFrameRecord.unpack(chunk, validate_crc=True)
                    # Check validity flag
                    if not (record.quality_flags & FLAG_VALID):
                        if stop_on_error:
                            self.corrupted_records += 1
                            break

                    # Monotonicity check
                    if record.capture_qpc_us < prev_qpc:
                        if stop_on_error:
                            self.corrupted_records += 1
                            break

                    prev_qpc = record.capture_qpc_us
                    self.records.append(record)
                    self.valid_records_count += 1
                    self.valid_bytes_offset += RECORD_SIZE_V1
                except Exception:
                    self.corrupted_records += 1
                    if stop_on_error:
                        break

        return self.records

    def repair_and_truncate(self) -> int:
        """Truncate any corrupted or partial bytes after the last valid record and mark clean closed."""
        if not self.path.is_file():
            return 0
        file_size = self.path.stat().st_size
        bytes_truncated = 0
        if file_size > self.valid_bytes_offset:
            with open(self.path, "r+b") as f:
                f.truncate(self.valid_bytes_offset)
            bytes_truncated = file_size - self.valid_bytes_offset

        # Update header to clean closed if we have valid header
        if self.header is not None and self.valid_bytes_offset >= HEADER_SIZE_V1:
            try:
                self.header.header_flags |= FLAG_HEADER_CLEAN_CLOSED
                with open(self.path, "r+b") as f:
                    f.seek(0)
                    f.write(self.header.pack())
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                pass
        return bytes_truncated


def verify_segment_alignment(
    jti_path: Path | str,
    mp4_path: Path | str | None = None,
) -> dict[str, Any]:
    """Inspect cross-verification alignment between JTI1 sidecar and MP4 container.

    Checks:
      1. JTI existence and validity of frame records.
      2. MP4 existence and decodability of all frames.
      3. Alignment between record segment_sample_idx and decodable MP4 frames.
      4. Inaccessible sample indices where JTI references video frames that do not exist in MP4.
      5. Verification of PTS monotonicity and video_pts_us correspondence.
    """
    jti_p = Path(jti_path)
    if not jti_p.is_file():
        return {
            "aligned": False,
            "status": "missing_jti",
            "jti_records": 0,
            "mp4_frames": 0,
            "missing_frames_count": 0,
            "inaccessible_sample_indices": [],
            "pts_mismatches": [],
        }

    reader = TemporalIndexReader(jti_p)
    records = reader.read_all_records(stop_on_error=True)

    mp4_frames = 0
    mp4_pts_list: list[int] = []
    mp4_exists = False

    if mp4_path is not None:
        mp4_p = Path(mp4_path)
        if mp4_p.is_file() and mp4_p.stat().st_size > 0:
            mp4_exists = True
            try:
                import av
                with av.open(str(mp4_p)) as container:
                    if container.streams.video:
                        stream = container.streams.video[0]
                        time_base = float(stream.time_base) if stream.time_base else (1.0 / 60.0)
                        for frame in container.decode(stream):
                            pts_us = int(frame.pts * time_base * 1_000_000) if frame.pts is not None else -1
                            mp4_pts_list.append(pts_us)
                            mp4_frames += 1
            except Exception:
                # Video file was truncated or corrupt
                pass
    else:
        mp4_exists = True

    inaccessible_samples: list[int] = []
    pts_mismatches: list[dict[str, Any]] = []

    first_jti_pts: int | None = None
    first_mp4_pts: int | None = None
    for r in records:
        if r.segment_sample_idx == 0 and r.video_pts_us >= 0:
            first_jti_pts = r.video_pts_us
            break
    if first_jti_pts is None:
        for r in records:
            if r.segment_sample_idx >= 0 and r.video_pts_us >= 0:
                first_jti_pts = r.video_pts_us
                break
    if mp4_pts_list and mp4_pts_list[0] >= 0:
        first_mp4_pts = mp4_pts_list[0]

    for r in records:
        if r.segment_sample_idx >= 0:
            if r.segment_sample_idx >= mp4_frames:
                inaccessible_samples.append(r.segment_sample_idx)
            elif (
                mp4_frames > 0
                and r.segment_sample_idx < len(mp4_pts_list)
                and mp4_pts_list[r.segment_sample_idx] >= 0
                and r.video_pts_us >= 0
                and first_jti_pts is not None
                and first_mp4_pts is not None
            ):
                jti_rel_us = r.video_pts_us - first_jti_pts
                mp4_rel_us = mp4_pts_list[r.segment_sample_idx] - first_mp4_pts
                diff_us = abs(jti_rel_us - mp4_rel_us)
                if diff_us > 100_000:  # >100ms PTS divergence
                    pts_mismatches.append({
                        "capture_frame_id": r.capture_frame_id,
                        "sample_idx": r.segment_sample_idx,
                        "jti_pts_us": r.video_pts_us,
                        "mp4_pts_us": mp4_pts_list[r.segment_sample_idx],
                        "diff_us": diff_us,
                    })

    aligned = (
        len(inaccessible_samples) == 0
        and len(pts_mismatches) == 0
        and not reader.is_truncated
        and (mp4_path is None or (mp4_exists and (mp4_frames > 0 if len(records) > 0 else True)))
    )

    return {
        "aligned": aligned,
        "status": "aligned" if aligned else "misaligned",
        "jti_records": len(records),
        "mp4_frames": mp4_frames,
        "missing_frames_count": len(inaccessible_samples),
        "inaccessible_sample_indices": inaccessible_samples,
        "pts_mismatches": pts_mismatches,
    }


def repair_and_finalize(
    jti_path: Path | str,
    mp4_path: Path | str | None = None,
) -> dict[str, Any]:
    """Synchronized crash-repair for .jti sidecar and corresponding .mp4 container.

    Invariants:
      1. Validates all JTI records up to the first corrupted or truncated record.
      2. If mp4_path is provided, inspects decodable video frame count in MP4.
         If MP4 is missing, 0 bytes, or unopenable, mp4_frame_count is strictly 0.
      3. Synchronizes JTI with MP4: any JTI records beyond decodable MP4 frames
         are truncated so JTI sample indices never exceed decodable frames.
      4. Truncates uncommitted/corrupted tail bytes from JTI file.
      5. Updates IndexSegmentHeader with FLAG_HEADER_CLEAN_CLOSED and recomputed CRC32.
      6. Returns repair summary statistics.
    """
    jti_p = Path(jti_path)
    if not jti_p.is_file():
        return {
            "status": "error",
            "reason": f"File not found: {jti_path}",
            "valid_records": 0,
            "truncated_records": 0,
            "mp4_frames": 0,
        }

    reader = TemporalIndexReader(jti_p)
    records = reader.read_all_records(stop_on_error=True)

    # 1. Inspect MP4 if provided
    mp4_frame_count: int | None = None
    if mp4_path is not None:
        mp4_p = Path(mp4_path)
        mp4_frame_count = 0
        if mp4_p.is_file() and mp4_p.stat().st_size > 0:
            try:
                import av
                with av.open(str(mp4_p)) as container:
                    if container.streams.video:
                        stream = container.streams.video[0]
                        for _ in container.decode(stream):
                            mp4_frame_count += 1
            except Exception:
                pass

    # 2. Determine synchronized cutoff
    valid_records_to_keep = len(records)
    if mp4_frame_count is not None:
        encoded_seen = 0
        cutoff_idx = 0
        for i, rec in enumerate(records):
            if rec.segment_sample_idx >= 0:
                if encoded_seen >= mp4_frame_count:
                    break
                encoded_seen += 1
            cutoff_idx = i + 1
        valid_records_to_keep = cutoff_idx

    new_valid_offset = HEADER_SIZE_V1 + valid_records_to_keep * RECORD_SIZE_V1
    file_size = jti_p.stat().st_size
    bytes_to_truncate = max(0, file_size - new_valid_offset)

    if bytes_to_truncate > 0:
        with open(jti_p, "r+b") as f:
            f.truncate(new_valid_offset)

    # 3. Clean close the header
    if reader.header is not None and new_valid_offset >= HEADER_SIZE_V1:
        reader.header.header_flags |= FLAG_HEADER_CLEAN_CLOSED
        with open(jti_p, "r+b") as f:
            f.seek(0)
            f.write(reader.header.pack())
            f.flush()
            os.fsync(f.fileno())

    truncated_records = len(records) - valid_records_to_keep
    return {
        "status": "repaired",
        "valid_records": valid_records_to_keep,
        "truncated_records": truncated_records,
        "bytes_truncated": bytes_to_truncate,
        "mp4_frames": mp4_frame_count if mp4_frame_count is not None else 0,
        "clean_closed": True,
    }
