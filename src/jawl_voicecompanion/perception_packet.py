"""Small AV evidence packet shared by Companion and the owned native context."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

OPEN = "\n\n<va_perception>\n"
CLOSE = "\n</va_perception>"
_LEGACY = re.compile(
    r"\s+\[(?:ФОН ВОСПРИЯТИЯ|ТЕКУЩЕЕ ВИЗУАЛЬНОЕ ОСНОВАНИЕ|Свежих наблюдений восприятия нет)",
    re.I,
)
_LABELS = {"screen": "Видео", "window": "Окно/UIA", "speech": "Речь из медиа",
           "music": "Музыка", "sound": "Звуки", "media": "Описание AV", "ocr": "OCR",
           "music_candidate": "Возможный музыкальный/тональный фон",
           "audio_description": "Описание аудио", "audio_candidates": "Аудиотеги-кандидаты",
           "eg2": "AV-теги", "eg2_media": "AV-теги"}


_LABELS["audio_event_candidates"] = "YAMNet sound-event hypotheses"
_LABELS["voice_delivery"] = "\u0410\u043a\u0443\u0441\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u043f\u0440\u0438\u0437\u043d\u0430\u043a\u0438 \u0433\u043e\u043b\u043e\u0441\u0430"


def strip_appendix(text: str) -> str:
    value = str(text or "")
    positions = [p for p in (value.find("<va_perception>"),) if p >= 0]
    old = _LEGACY.search(value)
    if old:
        positions.append(old.start())
    return value[:min(positions)].rstrip() if positions else value


def split_packet(text: str) -> tuple[str, dict[str, Any]]:
    value = str(text or "")
    start = value.find("<va_perception>")
    closing = value.rfind("</va_perception>")
    if start < 0 or closing < start or value[closing + len("</va_perception>"):].strip():
        return value, {}
    # Native ChatBridge flattens literal newlines before its TCP write. JSON
    # string escapes survive, so markers must not depend on line boundaries.
    raw = value[start + len("<va_perception>"):closing].strip()
    if len(raw) > 32000:
        return value, {}
    try:
        packet = json.loads(raw)
    except (ValueError, TypeError):
        return value, {}
    if not isinstance(packet, dict) or packet.get("version") != 1:
        return value, {}
    return value[:start].rstrip(), packet


def make_packet(snapshot: dict[str, Any], *, fallback: str = "", history: str = "") -> dict[str, Any]:
    packet: dict[str, Any] = {"version": 1, "generated_at": time.time(), "channels": {}}
    channels = snapshot.get("channels")
    if isinstance(channels, dict):
        for kind, label in _LABELS.items():
            if kind in {"eg2", "eg2_media"} and snapshot.get("include_eg2_media_in_scene") is False:
                continue
            source = channels.get(kind)
            if not isinstance(source, dict) or not str(source.get("text") or "").strip():
                continue
            metadata = source.get("metadata") or {}
            if kind == "music" and metadata.get("music_state") in {"unknown", "unconfirmed", "no_music"} and not metadata.get("candidate_tags"):
                continue  # Unknown detector state carries no descriptive evidence.
            packet["channels"][kind] = {
                "text": str(source["text"]).replace("\x00", "").strip(),
                "age_s": max(0, float(source.get("age_ms") or 0) / 1000),
                "ttl_s": max(0, float(source.get("ttl_ms") or 0) / 1000),
                "hypothesis": kind == "screen" or metadata.get("verified") is False or bool(metadata.get("candidate_tags") and metadata.get("candidate_tags_calibrated") is False),
                "possibly_outdated": bool(metadata.get("possibly_outdated")),
            }
            tags = metadata.get("candidate_tags")
            ended = metadata.get("segment_ended_monotonic")
            captured = snapshot.get("captured_monotonic")
            if isinstance(ended, (int, float)) and isinstance(captured, (int, float)):
                packet["channels"][kind]["age_s"] = max(packet["channels"][kind]["age_s"], captured - ended)
            if isinstance(tags, (list, tuple)) and tags:
                packet["channels"][kind]["candidate_tags"] = [str(tag)[:80] for tag in tags[:6]]
            duration = metadata.get("duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                packet["channels"][kind]["duration_s"] = max(0, duration / 1000)
            if kind == "screen" and source.get("caption_age_ms") is not None:
                packet["channels"][kind]["caption_age_s"] = float(source["caption_age_ms"]) / 1000
    if not packet["channels"] and not channels and fallback:
        packet["summary"] = str(fallback).strip()
    if history:
        packet["history"] = history
    return packet


def attach_packet(text: str, packet: dict[str, Any]) -> str:
    return text + OPEN + json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + CLOSE


def render_packet(packet: dict[str, Any], *, now: float | None = None) -> str:
    """Use only substantive evidence and age; diagnostics remain in sensor state."""
    current = time.time() if now is None else now
    elapsed = max(0, current - float(packet.get("generated_at") or current))
    lines = []
    channels = packet.get("channels") or {}
    for kind, label in _LABELS.items():
        entry = channels.get(kind)
        if not isinstance(entry, dict):
            continue
        age = max(0, float(entry.get("age_s") or 0) + elapsed)
        stale = age > float(entry.get("ttl_s") or 0) or entry.get("possibly_outdated")
        if stale and (kind != "screen" or age > 90):
            continue
        state = "; последнее наблюдение, сцена могла измениться" if stale else ""
        uncertainty = "; гипотеза модели" if entry.get("hypothesis") else ""
        duration = f"; фрагмент {entry['duration_s']:.1f} с" if entry.get("duration_s") else ""
        caption_age = f"; описание {entry['caption_age_s'] + elapsed:.1f} с назад" if entry.get("caption_age_s") else ""
        tags = "; теги-кандидаты: " + ", ".join(entry["candidate_tags"]) if entry.get("candidate_tags") else ""
        lines.append(f"{label} ({age:.1f} с назад{caption_age}{duration}{state}{uncertainty}): {entry.get('text', '')}{tags}")
    if packet.get("summary") and elapsed <= 20:
        lines.append(str(packet["summary"]))
    if packet.get("history"):
        lines.append("История наблюдений (не текущая сцена):\n" + str(packet["history"]))
    return "\n".join(lines)


def save_packet(path: Path, packet: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".perception-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(packet, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_owned_packet() -> dict[str, Any]:
    """Read the owned sensor handoff, never configuration or environment secrets."""
    home = os.environ.get("JAWL_INSTANCE_HOME", "")
    if not home or not Path(home).is_absolute():
        return {}
    path = Path(home) / "data" / "sensory" / "current-perception.json"
    try:
        if path.is_symlink() or path.stat().st_size > 32000:
            return {}
        packet = json.loads(path.read_text(encoding="utf-8"))
        return packet if isinstance(packet, dict) and packet.get("version") == 1 else {}
    except (OSError, ValueError):
        return {}
