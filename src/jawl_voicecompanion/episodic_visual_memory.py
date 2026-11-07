"""Episodic Visual Memory with LanceDB and Dual Multimodal Embeddings.

Implements the MemoryOS / A-MEM hierarchical visual memory tier:
- Stores compressed keyframe thumbnails (.webp) in an on-disk cache.
- Generates 512-dim multimodal visual embeddings (CLIP ViT-B/32 ONNX).
- Persists structured metadata (window, speech, valence/arousal, scene_id) in LanceDB.
- Enables natural language visual semantic retrieval ("guy with a sword and red cloak")
  even when initial VLM descriptions missed fine visual nuances.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, List, Optional, Tuple
import uuid

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Ensure NO_PROXY does not contain brackets like [::1] which break httpx / huggingface_hub
for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var, "")
    if "[::1]" in _val or "::1" in _val:
        _clean = ",".join(p.strip() for p in _val.split(",") if p.strip() not in ("::1", "[::1]"))
        os.environ[_var] = _clean or "127.0.0.1,localhost"

try:
    import lancedb
    import pyarrow as pa
    _LANCEDB_AVAILABLE = True
except Exception:
    lancedb = None
    pa = None
    _LANCEDB_AVAILABLE = False

try:
    from fastembed import ImageEmbedding, TextEmbedding
    _FASTEMBED_AVAILABLE = True
except Exception:
    ImageEmbedding = None
    TextEmbedding = None
    _FASTEMBED_AVAILABLE = False

_DEFAULT_MULTILINGUAL_MODEL = "jinaai/jina-clip-v1"
_FALLBACK_IMAGE_MODEL = "Qdrant/clip-ViT-B-32-vision"
_FALLBACK_TEXT_MODEL = "Qdrant/clip-ViT-B-32-text"
_DEFAULT_IMAGE_MODEL = _DEFAULT_MULTILINGUAL_MODEL
_DEFAULT_TEXT_MODEL = _DEFAULT_MULTILINGUAL_MODEL
_VECTOR_DIM = 768


def get_time_of_day(hour: int | None = None) -> str:
    """Return Russian time of day category."""
    if hour is None:
        import datetime
        hour = datetime.datetime.now().hour
    if 5 <= hour < 12:
        return "утро"
    elif 12 <= hour < 18:
        return "день"
    elif 18 <= hour < 23:
        return "вечер"
    else:
        return "ночь"


class EpisodicVisualMemory:
    """Embedded LanceDB vector database for streaming keyframes and multimodal retrieval."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        image_cache_dir: str | Path | None = None,
        table_name: str = "keyframes",
        taste_table_name: str = "taste_profile",
        model_name: str = _DEFAULT_MULTILINGUAL_MODEL,
        max_image_dimension: int = 720,
        webp_quality: int = 80,
        max_cached_keyframes: int = 1000,
        max_cache_mb: float = 200.0,
        retention_seconds: float = 3 * 86400.0,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.table_name = str(table_name)
        self.taste_table_name = str(taste_table_name)
        self.model_name = str(model_name)
        self.max_image_dimension = max(128, min(int(max_image_dimension), 1920))
        self.webp_quality = max(20, min(int(webp_quality), 100))
        self.vector_dim = 768 if "jina" in self.model_name.lower() else 512
        self.max_cached_keyframes = max(10, int(max_cached_keyframes))
        self.max_cache_bytes = int(max(1.0, float(max_cache_mb)) * 1024 * 1024)
        self.retention_seconds = max(60.0, float(retention_seconds))
        self._ingest_counter = 0

        if image_cache_dir is not None:
            self.image_cache_dir = Path(image_cache_dir).resolve()
        elif self.db_path.name == "lancedb":
            self.image_cache_dir = self.db_path.parent / "keyframe_cache"
        else:
            self.image_cache_dir = self.db_path / "keyframe_cache"

        self.image_cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._db: Any = None
        self._table: Any = None
        self._taste_table: Any = None
        self._image_model: Any = None
        self._text_model: Any = None

        self._init_storage()

    def _init_storage(self) -> None:
        if not _LANCEDB_AVAILABLE or lancedb is None or pa is None:
            raise RuntimeError("lancedb and pyarrow are required for EpisodicVisualMemory")

        with self._lock:
            self._db = lancedb.connect(str(self.db_path))
            if hasattr(self._db, "list_tables"):
                existing_tables = list(self._db.list_tables())
            else:
                existing_tables = self._db.table_names()

            if self.table_name in existing_tables:
                self._table = self._db.open_table(self.table_name)
                try:
                    f = self._table.schema.field("vector")
                    if hasattr(f.type, "list_size"):
                        self.vector_dim = f.type.list_size
                except Exception:
                    pass
            else:
                schema = pa.schema([
                    pa.field("vector", pa.list_(pa.float32(), self.vector_dim)),
                    pa.field("scene_id", pa.string()),
                    pa.field("timestamp", pa.float64()),
                    pa.field("image_path", pa.string()),
                    pa.field("app_name", pa.string()),
                    pa.field("window_title", pa.string()),
                    pa.field("speech_context", pa.string()),
                    pa.field("summary", pa.string()),
                    pa.field("valence", pa.float32()),
                    pa.field("arousal", pa.float32()),
                    pa.field("metadata_json", pa.string()),
                ])
                self._table = self._db.create_table(self.table_name, schema=schema)

            # Taste profile table for SMTC + audio descriptor + time of day
            if self.taste_table_name in existing_tables:
                self._taste_table = self._db.open_table(self.taste_table_name)
            else:
                taste_schema = pa.schema([
                    pa.field("track_title", pa.string()),
                    pa.field("artist", pa.string()),
                    pa.field("album", pa.string()),
                    pa.field("time_of_day", pa.string()),
                    pa.field("timestamp", pa.float64()),
                    pa.field("valence", pa.float32()),
                    pa.field("arousal", pa.float32()),
                    pa.field("audio_vector", pa.list_(pa.float32(), 16)),
                    pa.field("metadata_json", pa.string()),
                ])
                self._taste_table = self._db.create_table(self.taste_table_name, schema=taste_schema)

    def _get_image_model(self) -> Any:
        if self._image_model is None:
            if not _FASTEMBED_AVAILABLE or ImageEmbedding is None:
                raise RuntimeError("fastembed ImageEmbedding is not available")
            try:
                self._image_model = ImageEmbedding(model_name=self.model_name)
            except Exception as exc:
                logger.warning("Failed to load image model '%s', falling back to '%s': %s",
                               self.model_name, _FALLBACK_IMAGE_MODEL, exc)
                self.model_name = _FALLBACK_IMAGE_MODEL
                self.vector_dim = 512
                self._image_model = ImageEmbedding(model_name=_FALLBACK_IMAGE_MODEL)
        return self._image_model

    def _get_text_model(self) -> Any:
        if self._text_model is None:
            if not _FASTEMBED_AVAILABLE or TextEmbedding is None:
                raise RuntimeError("fastembed TextEmbedding is not available")
            try:
                self._text_model = TextEmbedding(model_name=self.model_name)
            except Exception as exc:
                logger.warning("Failed to load text model '%s', falling back to '%s': %s",
                               self.model_name, _FALLBACK_TEXT_MODEL, exc)
                self.model_name = _FALLBACK_TEXT_MODEL
                self.vector_dim = 512
                self._text_model = TextEmbedding(model_name=_FALLBACK_TEXT_MODEL)
        return self._text_model

    def _prepare_pil_image(self, frame: np.ndarray | Image.Image) -> Image.Image:
        if isinstance(frame, np.ndarray):
            img = Image.fromarray(frame, mode="RGB")
        elif isinstance(frame, Image.Image):
            img = frame.convert("RGB")
        else:
            raise TypeError(f"Expected numpy ndarray or PIL Image, got {type(frame)}")

        w, h = img.size
        if max(w, h) > self.max_image_dimension:
            scale = float(self.max_image_dimension) / float(max(w, h))
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

        return img

    def ingest_keyframe(
        self,
        frame: np.ndarray | Image.Image,
        *,
        scene_id: str,
        timestamp: float | None = None,
        app_name: str = "",
        window_title: str = "",
        speech_context: str = "",
        summary: str = "",
        valence: float = 0.0,
        arousal: float = 0.0,
        extra_metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compress, embed, and store a keyframe with its episodic context."""
        now = time.time() if timestamp is None else float(timestamp)
        img = self._prepare_pil_image(frame)

        # Sanitize scene_id and prevent directory traversal / path escape
        raw_sid = str(scene_id or "scene").strip()
        clean_sid = "".join(c for c in raw_sid if c.isalnum() or c in ("-", "_")).strip("._-")
        if not clean_sid:
            clean_sid = "scene"

        # 1. Save compressed WebP image to disk
        uid = uuid.uuid4().hex[:6]
        filename = f"{clean_sid}_{int(now * 1000)}_{uid}.webp"
        cache_root = self.image_cache_dir.resolve()
        target_path = (self.image_cache_dir / filename).resolve()

        # Guard against directory escape on ingest
        try:
            is_inside = target_path.is_relative_to(cache_root)
        except AttributeError:
            try:
                target_path.relative_to(cache_root)
                is_inside = True
            except ValueError:
                is_inside = False

        if not is_inside or target_path.parent != cache_root:
            raise ValueError(f"Path escape attempted with scene_id '{scene_id}'")

        img.save(str(target_path), format="WEBP", quality=self.webp_quality, method=4)

        # 2. Compute 512-dim multimodal embedding in memory via BytesIO
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)

        try:
            with self._lock:
                model = self._get_image_model()
                embs = list(model.embed([buf]))
                raw_vec = embs[0].astype(np.float32)
                norm = np.linalg.norm(raw_vec)
                if norm > 1e-6:
                    raw_vec = raw_vec / norm
                vec_list = raw_vec.tolist()

                # 3. Insert record into LanceDB
                meta_dict = dict(extra_metadata or {})
                if event_id is not None and str(event_id).strip():
                    meta_dict["event_id"] = str(event_id).strip()
                if evidence_ids is not None:
                    clean_evs = [str(e).strip() for e in evidence_ids if str(e).strip()]
                    if clean_evs:
                        meta_dict["evidence_ids"] = clean_evs
                meta_json = json.dumps(meta_dict, ensure_ascii=False)
                row = {
                    "vector": vec_list,
                    "scene_id": clean_sid,
                    "timestamp": float(now),
                    "image_path": str(target_path),
                    "app_name": str(app_name or "")[:120],
                    "window_title": str(window_title or "")[:250],
                    "speech_context": str(speech_context or "")[:500],
                    "summary": str(summary or "")[:500],
                    "valence": float(max(-1.0, min(float(valence), 1.0))),
                    "arousal": float(max(-1.0, min(float(arousal), 1.0))),
                    "metadata_json": meta_json,
                }
                self._table.add([row])
        except Exception as exc:
            # Prevent orphan webp file on disk if embedding or LanceDB write fails
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise exc

        self._ingest_counter += 1
        if self._ingest_counter % 25 == 0:
            try:
                self.cleanup_old_keyframes()
            except Exception as exc:
                logger.warning("Auto cleanup of old keyframes failed: %s", exc)

        res = {
            "status": "ingested",
            "scene_id": scene_id,
            "timestamp": now,
            "image_path": str(target_path.resolve()),
            "vector_dim": len(vec_list),
        }
        if meta_dict.get("event_id"):
            res["event_id"] = meta_dict["event_id"]
        return res

    def search_visual(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[dict[str, Any]]:
        """Natural language visual retrieval using aligned multimodal text embedding."""
        if not str(query or "").strip():
            return []

        with self._lock:
            text_model = self._get_text_model()
            text_embs = list(text_model.embed([str(query).strip()]))
            raw_vec = text_embs[0].astype(np.float32)
            norm = np.linalg.norm(raw_vec)
            if norm > 1e-6:
                raw_vec = raw_vec / norm

            # LanceDB vector search with cosine metric
            results = (
                self._table.search(raw_vec)
                .metric("cosine")
                .limit(max(1, min(int(top_k), 50)))
                .to_list()
            )

        output = []
        for r in results:
            dist = float(r.get("_distance", 1.0))
            # Cosine distance = 1 - cosine_similarity
            similarity = max(-1.0, min(1.0, 1.0 - dist))
            if similarity < min_score:
                continue

            meta = {}
            if r.get("metadata_json"):
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass

            item = {
                "similarity": round(similarity, 4),
                "distance": round(dist, 4),
                "scene_id": r.get("scene_id"),
                "timestamp": r.get("timestamp"),
                "image_path": r.get("image_path"),
                "webp_path": r.get("image_path"),
                "app_name": r.get("app_name"),
                "window_title": r.get("window_title"),
                "speech_context": r.get("speech_context"),
                "summary": r.get("summary"),
                "entity_summary": r.get("summary"),
                "valence": r.get("valence"),
                "arousal": r.get("arousal"),
                "metadata": meta,
            }
            output.append(item)

        output.sort(key=lambda x: x["similarity"], reverse=True)
        return output

    def recall_visual_detail(
        self,
        user_query: str,
        vlm_client: Any = None,
        *,
        top_k: int = 2,
    ) -> str:
        """Visual Recall Loop: retrieves top-k keyframes via SigLIP/multilingual CLIP and inspects with VLM."""
        hits = self.search_visual(user_query, top_k=top_k)
        if not hits:
            return "В памяти нет подходящих кадров."

        images = [hit.get("webp_path") or hit.get("image_path", "") for hit in hits]
        context_notes = [hit.get("entity_summary") or hit.get("summary", "") for hit in hits]

        prompt = (
            f"Вопрос пользователя: '{user_query}'. "
            f"Контекст сцены: {context_notes}. "
            f"Опиши мельчайшие визуальные детали с этих кадров."
        )

        if vlm_client is not None:
            if hasattr(vlm_client, "analyze_images"):
                return str(vlm_client.analyze_images(images, prompt))
            elif callable(vlm_client):
                return str(vlm_client(images, prompt))

        return f"[VISUAL_RECALL]\nКадры: {images}\nПромпт: {prompt}"

    def save_taste_record(
        self,
        track_info: dict[str, Any],
        *,
        audio_vector: list[float] | None = None,
        time_of_day: str | None = None,
        valence: float = 0.0,
        arousal: float = 0.0,
    ) -> dict[str, Any]:
        """Save music taste record: track metadata + acoustic vector + time of day."""
        tod = time_of_day or get_time_of_day()
        now = time.time()
        vec = audio_vector if (audio_vector and len(audio_vector) == 16) else [0.0] * 16
        vec = [float(x) for x in vec[:16]]

        row = {
            "track_title": str(track_info.get("title", "Unknown Track"))[:200],
            "artist": str(track_info.get("artist", "Unknown Artist"))[:150],
            "album": str(track_info.get("album", ""))[:150],
            "time_of_day": str(tod),
            "timestamp": float(now),
            "valence": float(max(-1.0, min(float(valence), 1.0))),
            "arousal": float(max(-1.0, min(float(arousal), 1.0))),
            "audio_vector": vec,
            "metadata_json": json.dumps(track_info, ensure_ascii=False),
        }

        with self._lock:
            if self._taste_table is not None:
                self._taste_table.add([row])

        return {"status": "saved", "track": row["track_title"], "time_of_day": tod}

    def get_recent_taste_records(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            if self._taste_table is None or len(self._taste_table) == 0:
                return []
            records = self._taste_table.to_arrow().to_pylist()
            records.sort(key=lambda x: x.get("timestamp", 0.0), reverse=True)
            return records[:max(1, int(limit))]

    def cleanup_old_keyframes(
        self,
        *,
        max_age_seconds: float | None = None,
        max_count: int | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, int]:
        """Prune keyframes from disk cache and LanceDB by age, count, or disk budget."""
        now = time.time()
        ttl = float(max_age_seconds) if max_age_seconds is not None else self.retention_seconds
        allowed_count = int(max_count) if max_count is not None else self.max_cached_keyframes
        allowed_bytes = int(max_bytes) if max_bytes is not None else self.max_cache_bytes

        deleted_files = 0
        reclaimed_bytes = 0
        deleted_scene_ids: set[str] = set()

        with self._lock:
            # 1. Enumerate all cached WebP files
            file_entries = []
            try:
                for entry in self.image_cache_dir.glob("*.webp"):
                    if entry.is_file():
                        stat = entry.stat()
                        file_entries.append((entry, stat.st_mtime, stat.st_size))
            except Exception as exc:
                logger.warning("Failed listing keyframe cache files: %s", exc)
                return {"deleted_files": 0, "reclaimed_bytes": 0, "remaining_files": 0}

            # 2. Identify expired files by mtime
            cutoff = now - ttl
            remaining_entries = []
            deleted_image_paths: set[str] = set()

            for path, mtime, size in file_entries:
                if mtime < cutoff:
                    try:
                        path.unlink(missing_ok=True)
                        deleted_files += 1
                        reclaimed_bytes += size
                        deleted_image_paths.add(str(path.resolve()))
                    except Exception:
                        remaining_entries.append((path, mtime, size))
                else:
                    remaining_entries.append((path, mtime, size))

            # 3. Prune if count exceeds allowed_count (oldest first)
            if len(remaining_entries) > allowed_count:
                remaining_entries.sort(key=lambda x: x[1])
                excess = len(remaining_entries) - allowed_count
                to_delete = remaining_entries[:excess]
                remaining_entries = remaining_entries[excess:]
                for path, mtime, size in to_delete:
                    try:
                        path.unlink(missing_ok=True)
                        deleted_files += 1
                        reclaimed_bytes += size
                        deleted_image_paths.add(str(path.resolve()))
                    except Exception:
                        pass

            # 4. Prune if total size exceeds allowed_bytes (oldest first)
            total_size = sum(x[2] for x in remaining_entries)
            if total_size > allowed_bytes:
                remaining_entries.sort(key=lambda x: x[1])
                idx = 0
                while idx < len(remaining_entries) and total_size > allowed_bytes:
                    path, mtime, size = remaining_entries[idx]
                    try:
                        path.unlink(missing_ok=True)
                        deleted_files += 1
                        reclaimed_bytes += size
                        total_size -= size
                        deleted_image_paths.add(str(path.resolve()))
                    except Exception:
                        pass
                    idx += 1
                remaining_entries = remaining_entries[idx:]

            # 5. Synchronize LanceDB table strictly by exact image_path and cutoff
            if self._table is not None and (deleted_image_paths or deleted_files > 0):
                try:
                    if cutoff > 0:
                        self._table.delete(f"timestamp < {cutoff}")
                    if deleted_image_paths:
                        paths_list = list(deleted_image_paths)
                        batch_size = 50
                        for i in range(0, len(paths_list), batch_size):
                            batch = paths_list[i : i + batch_size]
                            escaped = [p.replace("'", "''") for p in batch]
                            in_clause = ", ".join(f"'{p}'" for p in escaped)
                            self._table.delete(f"image_path IN ({in_clause})")
                except Exception as exc:
                    logger.warning("Failed pruning LanceDB rows: %s", exc)

            return {
                "deleted_files": deleted_files,
                "reclaimed_bytes": reclaimed_bytes,
                "remaining_files": len(remaining_entries),
            }

    def delete_keyframe(self, scene_id: str | None = None, *, image_path: str | None = None) -> bool:
        """Explicitly remove keyframes by scene_id or specific image_path with strict boundary enforcement."""
        found = False
        with self._lock:
            cache_root = self.image_cache_dir.resolve()

            if image_path:
                try:
                    raw_target = Path(image_path)
                    target_p = raw_target.resolve()
                except Exception as exc:
                    logger.warning("Invalid image_path format '%s': %s", image_path, exc)
                    return False

                # P0 Boundary Check: path MUST be strictly inside cache_root, not cache_root itself, and parent must be cache_root
                try:
                    is_inside = target_p.is_relative_to(cache_root)
                except AttributeError:
                    try:
                        target_p.relative_to(cache_root)
                        is_inside = True
                    except ValueError:
                        is_inside = False

                if not is_inside or target_p == cache_root or target_p.parent != cache_root:
                    logger.warning("Security denial: attempt to delete file outside image_cache_dir: '%s'", image_path)
                    return False

                # Reject symlinks/reparse points pointing outside or escaping cache_root
                if raw_target.is_symlink():
                    try:
                        link_target = raw_target.readlink()
                        resolved_link = (raw_target.parent / link_target).resolve()
                        if not resolved_link.is_relative_to(cache_root) or resolved_link.parent != cache_root:
                            logger.warning("Security denial: symlink target escapes image_cache_dir: '%s'", image_path)
                            return False
                    except Exception as exc:
                        logger.warning("Failed resolving symlink '%s': %s", image_path, exc)
                        return False

                if target_p.suffix.lower() != ".webp":
                    logger.warning("Security denial: attempt to delete non-webp file: '%s'", image_path)
                    return False

                file_existed = target_p.is_file()
                file_deleted = False
                if file_existed:
                    try:
                        target_p.unlink(missing_ok=True)
                        file_deleted = True
                    except (PermissionError, OSError) as exc:
                        logger.warning("Failed to unlink locked keyframe file '%s': %s", target_p, exc)
                        return False

                table_deleted = False
                if self._table is not None:
                    try:
                        native_str = str(target_p).replace("'", "''")
                        posix_str = target_p.as_posix().replace("'", "''")
                        self._table.delete(f"image_path = '{native_str}' OR image_path = '{posix_str}'")
                        table_deleted = True
                    except Exception as exc:
                        logger.warning("Failed deleting keyframe by path %s from LanceDB: %s", image_path, exc)

                return file_deleted or table_deleted

            target_scene_id = str(scene_id or "").strip()
            if not target_scene_id:
                return False

            clean_sid = "".join(c for c in target_scene_id if c.isalnum() or c in ("_", "-")).strip("._-")
            if not clean_sid:
                return False

            def _matches_scene_filename(filename: str, sid: str) -> bool:
                if not filename.endswith(".webp"):
                    return False
                stem = filename[:-5]
                parts = stem.rsplit("_", 2)
                if len(parts) == 3 and parts[1].isdigit():
                    return parts[0] == sid
                parts_legacy = stem.rsplit("_", 1)
                if len(parts_legacy) == 2 and parts_legacy[1].isdigit():
                    return parts_legacy[0] == sid
                return stem == sid

            deleted_any_file = False
            try:
                for p in self.image_cache_dir.iterdir():
                    if p.is_file() and _matches_scene_filename(p.name, clean_sid):
                        try:
                            p.unlink(missing_ok=True)
                            deleted_any_file = True
                        except Exception as exc:
                            logger.warning("Failed unlinking scene frame '%s': %s", p, exc)
            except Exception as exc:
                logger.warning("Failed enumerating cache for scene '%s': %s", clean_sid, exc)

            table_deleted = False
            if self._table is not None:
                try:
                    escaped_sid = clean_sid.replace("'", "''")
                    self._table.delete(f"scene_id = '{escaped_sid}'")
                    table_deleted = True
                except Exception as exc:
                    logger.warning("Failed deleting keyframe %s from LanceDB: %s", clean_sid, exc)

            return deleted_any_file or table_deleted

    def redact(self, identifiers: Any, *, reason: str = "") -> dict[str, Any]:
        """Redact keyframes and vector rows matching event_ids, scene_ids, evidence_ids, or image_paths.

        Strictly guarantees:
        1. Boundary confinement: files unlinked must reside strictly inside image_cache_dir.
        2. Zero orphan keyframe .webp files remain in image_cache_dir.
        3. Zero orphan vector rows remain in LanceDB keyframes table.
        """
        if isinstance(identifiers, (str, bytes)):
            identifiers = [identifiers]
        wanted = {str(item).strip() for item in (identifiers or []) if str(item or "").strip()}
        if not wanted:
            return {
                "status": "ignored",
                "reason": "no_identifiers",
                "event_ids": 0,
                "deleted_files": 0,
                "deleted_rows": 0,
            }

        with self._lock:
            cache_root = self.image_cache_dir.resolve()
            deleted_file_paths: set[str] = set()
            matching_image_paths: set[str] = set()
            matching_scene_ids: set[str] = set()

            def _is_safe_cache_child(p: Path) -> bool:
                try:
                    res = p.resolve()
                    try:
                        is_inside = res.is_relative_to(cache_root)
                    except AttributeError:
                        try:
                            res.relative_to(cache_root)
                            is_inside = True
                        except ValueError:
                            is_inside = False
                    return is_inside and res != cache_root and res.parent == cache_root
                except Exception:
                    return False

            # 1. Match against LanceDB rows (scene_id, image_path, metadata_json)
            if self._table is not None:
                try:
                    rows = self._table.to_arrow().to_pylist()
                except Exception as exc:
                    logger.warning("Failed reading LanceDB rows during redact: %s", exc)
                    rows = []

                for row in rows:
                    matched = False
                    sid = str(row.get("scene_id") or "")
                    img_p = str(row.get("image_path") or "")

                    if sid and sid in wanted:
                        matched = True
                    elif img_p and (img_p in wanted or Path(img_p).name in wanted):
                        matched = True
                    else:
                        meta_raw = row.get("metadata_json")
                        if meta_raw and isinstance(meta_raw, str):
                            try:
                                meta = json.loads(meta_raw)
                                if isinstance(meta, dict):
                                    eid = str(meta.get("event_id") or "").strip()
                                    if eid and eid in wanted:
                                        matched = True
                                    fid = str(meta.get("frame_id") or "").strip()
                                    if fid and fid in wanted:
                                        matched = True
                                    for key in ("evidence_ids", "source_event_ids", "identifiers"):
                                        val_list = meta.get(key)
                                        if isinstance(val_list, list):
                                            if any(str(v).strip() in wanted for v in val_list if str(v).strip()):
                                                matched = True
                                                break
                                    if not matched:
                                        for k, v in meta.items():
                                            if str(v).strip() in wanted or str(k).strip() in wanted:
                                                matched = True
                                                break
                            except (json.JSONDecodeError, TypeError):
                                pass

                    if matched:
                        if img_p:
                            matching_image_paths.add(img_p)
                        if sid:
                            matching_scene_ids.add(sid)

            # 2. Check direct path/filename matches in wanted
            for item in wanted:
                try:
                    raw_p = Path(item)
                    cand_p = raw_p if raw_p.is_absolute() else (self.image_cache_dir / item)
                    if _is_safe_cache_child(cand_p):
                        res_p = cand_p.resolve()
                        if res_p.is_symlink() or res_p.is_file():
                            res_p.unlink(missing_ok=True)
                            deleted_file_paths.add(str(res_p))
                            matching_image_paths.add(str(res_p))
                except Exception:
                    pass

            # 3. Unlink all matching image paths safely
            for img_p in list(matching_image_paths):
                try:
                    p = Path(img_p)
                    if _is_safe_cache_child(p):
                        res_p = p.resolve()
                        if (res_p.is_symlink() or res_p.is_file()) and str(res_p) not in deleted_file_paths:
                            res_p.unlink(missing_ok=True)
                            deleted_file_paths.add(str(res_p))
                except Exception as exc:
                    logger.warning("Failed unlinking matching keyframe '%s': %s", img_p, exc)

            # 4. Check scene_id filename patterns for all matching and wanted scene IDs
            def _matches_scene_filename(filename: str, sid: str) -> bool:
                if not filename.endswith(".webp"):
                    return False
                stem = filename[:-5]
                parts = stem.rsplit("_", 2)
                if len(parts) == 3 and parts[1].isdigit():
                    return parts[0] == sid
                parts_legacy = stem.rsplit("_", 1)
                if len(parts_legacy) == 2 and parts_legacy[1].isdigit():
                    return parts_legacy[0] == sid
                return stem == sid

            all_scenes = set(matching_scene_ids)
            for item in wanted:
                clean = "".join(c for c in item if c.isalnum() or c in ("-", "_")).strip("._-")
                if clean:
                    all_scenes.add(clean)

            try:
                for p in self.image_cache_dir.iterdir():
                    if p.is_file() and p.suffix.lower() == ".webp":
                        for sid in all_scenes:
                            if _matches_scene_filename(p.name, sid):
                                if _is_safe_cache_child(p):
                                    res_p = p.resolve()
                                    if str(res_p) not in deleted_file_paths:
                                        res_p.unlink(missing_ok=True)
                                        deleted_file_paths.add(str(res_p))
                                        matching_image_paths.add(str(res_p))
            except Exception as exc:
                logger.warning("Failed enumerating cache during redact scene unlink: %s", exc)

            # 5. Delete matching rows from LanceDB table
            deleted_rows = 0
            if self._table is not None:
                initial_count = len(self._table)
                # Delete by image_path
                if matching_image_paths:
                    paths_list = list(matching_image_paths)
                    batch_size = 50
                    for i in range(0, len(paths_list), batch_size):
                        batch = paths_list[i : i + batch_size]
                        escaped = [p.replace("'", "''") for p in batch]
                        in_clause = ", ".join(f"'{p}'" for p in escaped)
                        try:
                            self._table.delete(f"image_path IN ({in_clause})")
                        except Exception as exc:
                            logger.warning("Failed deleting LanceDB rows by image_path: %s", exc)

                # Delete by scene_id for matching scenes
                for sid in all_scenes:
                    if sid:
                        try:
                            esc_sid = sid.replace("'", "''")
                            self._table.delete(f"scene_id = '{esc_sid}'")
                        except Exception as exc:
                            logger.warning("Failed deleting LanceDB rows for scene '%s': %s", sid, exc)

                final_count = len(self._table)
                deleted_rows = max(0, initial_count - final_count)

            return {
                "status": "redacted",
                "event_ids": len(wanted),
                "reason": str(reason or "")[:120],
                "deleted_files": len(deleted_file_paths),
                "deleted_rows": deleted_rows,
            }

    def prune_taste_records(self, retention_seconds: float | None = None) -> int:
        """Remove taste profile records older than the retention threshold."""
        ttl = float(retention_seconds) if retention_seconds is not None else (7 * 86400.0)
        cutoff = time.time() - ttl
        with self._lock:
            if self._taste_table is None:
                return 0
            try:
                before_count = len(self._taste_table)
                self._taste_table.delete(f"timestamp < {cutoff}")
                after_count = len(self._taste_table)
                return max(0, before_count - after_count)
            except Exception as exc:
                logger.warning("Failed pruning taste table: %s", exc)
                return 0

    def clear_cache(self) -> dict[str, int]:
        """Completely purge the keyframe cache and truncate LanceDB tables."""
        with self._lock:
            deleted_files = 0
            reclaimed_bytes = 0
            for p in self.image_cache_dir.glob("*.webp"):
                try:
                    reclaimed_bytes += p.stat().st_size
                    p.unlink(missing_ok=True)
                    deleted_files += 1
                except Exception:
                    pass
            if self._table is not None:
                try:
                    self._table.delete("timestamp >= 0")
                except Exception:
                    pass
            if self._taste_table is not None:
                try:
                    self._taste_table.delete("timestamp >= 0")
                except Exception:
                    pass
            return {"deleted_files": deleted_files, "reclaimed_bytes": reclaimed_bytes}

    def count(self) -> int:
        with self._lock:
            return len(self._table)

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "db_path": str(self.db_path),
                "image_cache_dir": str(self.image_cache_dir),
                "table_name": self.table_name,
                "total_keyframes": self.count(),
                "vector_dimension": self.vector_dim,
                "model_name": self.model_name,
            }


def recall_visual_detail(
    user_query: str,
    vlm_client: Any = None,
    *,
    memory: EpisodicVisualMemory | None = None,
    lancedb_table: Any = None,
    top_k: int = 2,
) -> str:
    """Convenience functional recall hook."""
    if memory is not None:
        return memory.recall_visual_detail(user_query, vlm_client, top_k=top_k)
    elif lancedb_table is not None:
        try:
            hits = lancedb_table.search(user_query).limit(top_k).to_list()
        except Exception:
            return "В памяти нет подходящих кадров."
        if not hits:
            return "В памяти нет подходящих кадров."
        images = [h.get("webp_path") or h.get("image_path", "") for h in hits]
        context_notes = [h.get("entity_summary") or h.get("summary", "") for h in hits]
        prompt = (
            f"Вопрос пользователя: '{user_query}'. "
            f"Контекст сцены: {context_notes}. "
            f"Опиши мельчайшие визуальные детали с этих кадров."
        )
        if vlm_client is not None and hasattr(vlm_client, "analyze_images"):
            return str(vlm_client.analyze_images(images, prompt))
        elif vlm_client is not None and callable(vlm_client):
            return str(vlm_client(images, prompt))
        return f"[VISUAL_RECALL]\nКадры: {images}\nПромпт: {prompt}"
    return "В памяти нет подходящих кадров."
