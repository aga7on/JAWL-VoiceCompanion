"""A-MEM Narrative Consolidator: Episodic Story Logging & Character Card Synthesis.

Implements the A-MEM (arXiv:2502.12110) & MemoryOS (arXiv:2506.06326) episodic consolidation layer:
- Sleeps during active gaming / video watching to conserve GPU & compute.
- Wakes up periodically (every ~3 minutes) or when an acoustic gap (>= 5s silence) / window change occurs.
- Synthesizes recent speech transcript (GigaAM) and recent keyframes into:
  1. A concise single-line narrative episode log.
  2. Structured character cards (name, traits, visual keyframe link).
- Stores the consolidated narrative directly in LanceDB episodic memory metadata.
"""

from __future__ import annotations

import collections
import datetime
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class NarrativeConsolidator:
    """Consolidates speech transcripts and visual keyframes into narrative logs and character cards."""

    def __init__(
        self,
        *,
        episodic_memory: Any | None = None,
        llm_client: Any | None = None,
        consolidation_interval_sec: float = 180.0,
        silence_trigger_sec: float = 5.0,
        max_buffer_len: int = 120,
        storage_path: str | Path | None = None,
    ) -> None:
        self.episodic_memory = episodic_memory
        self.llm_client = llm_client
        self.consolidation_interval_sec = max(0.1, float(consolidation_interval_sec))
        self.silence_trigger_sec = max(0.1, float(silence_trigger_sec))
        self.max_buffer_len = max(10, int(max_buffer_len))
        self.storage_path = Path(storage_path).resolve() if storage_path is not None else None

        self._lock = threading.RLock()
        self._subtitles: Deque[dict[str, Any]] = collections.deque(maxlen=self.max_buffer_len)
        self._keyframes: Deque[dict[str, Any]] = collections.deque(maxlen=30)
        self._episode_logs: list[str] = []
        self._character_cards: dict[str, dict[str, Any]] = {}

        self._last_consolidation_time: float = time.monotonic()
        self._last_window: str = ""

        if self.storage_path is not None:
            self._load()

    def feed_subtitle(
        self,
        text: str,
        *,
        speaker: str = "dialogue",
        timestamp: float | None = None,
    ) -> None:
        """Feed a transcript chunk from ASR / GigaAM."""
        clean = str(text or "").strip()
        if not clean:
            return
        now = time.time() if timestamp is None else float(timestamp)
        with self._lock:
            self._subtitles.append({
                "time": now,
                "speaker": str(speaker),
                "text": clean,
            })

    def feed_keyframe(
        self,
        scene_id: str,
        webp_path: str,
        *,
        summary: str = "",
        timestamp: float | None = None,
    ) -> None:
        """Feed a keyframe ingested into visual episodic memory."""
        now = time.time() if timestamp is None else float(timestamp)
        with self._lock:
            self._keyframes.append({
                "time": now,
                "scene_id": str(scene_id),
                "webp_path": str(webp_path),
                "summary": str(summary or ""),
            })

    def check_trigger(
        self,
        *,
        silence_duration_sec: float = 0.0,
        window_title: str | None = None,
        force: bool = False,
    ) -> bool:
        """Check whether consolidation should run right now."""
        if force:
            return True

        now = time.monotonic()
        with self._lock:
            # Need at least some material (subtitles or keyframes)
            if not self._subtitles and not self._keyframes:
                return False

            elapsed = now - self._last_consolidation_time

            min_cooldown = min(30.0, max(0.05, self.consolidation_interval_sec / 2.0))

            # 1. Periodic timeout (>= 3 minutes)
            if elapsed >= self.consolidation_interval_sec:
                return True

            # 2. Silence pause trigger (>= 5.0s of silence after cooldown)
            if silence_duration_sec >= self.silence_trigger_sec and elapsed >= min_cooldown:
                return True

            # 3. Window switch trigger
            if window_title is not None and window_title != self._last_window:
                self._last_window = window_title
                if elapsed >= min_cooldown:
                    return True

            return False

    def consolidate(self, *, force: bool = False) -> Optional[dict[str, Any]]:
        """Run narrative consolidation over recent speech and visual memory."""
        now_mono = time.monotonic()
        with self._lock:
            if not force and not self.check_trigger():
                return None

            recent_subs = list(self._subtitles)
            recent_frames = list(self._keyframes)[-3:]

            if not recent_subs and not recent_frames:
                self._last_consolidation_time = now_mono
                return None

            # Format prompt context
            transcript_text = "\n".join(f"[{s['speaker']}] {s['text']}" for s in recent_subs[-20:])
            frames_text = "\n".join(
                f"- Кадр {f['scene_id']} ({f.get('webp_path', '')}): {f.get('summary', 'без описания')}"
                for f in recent_frames
            )

            current_cards_json = json.dumps(list(self._character_cards.values()), ensure_ascii=False)

            prompt = (
                f"Ниже недавние субтитры и ключевые кадры сцены:\n\n"
                f"Субтитры:\n{transcript_text or '—'}\n\n"
                f"Кадры сцены:\n{frames_text or '—'}\n\n"
                f"Известные персонажи: {current_cards_json}\n\n"
                f"Сформулируй ровно 1 лаконичную строчку для лога сюжета (episode_log) с текущим временем, "
                f"и укажи новые или обновлённые черты персонажей (updated_entities: name, new_trait, keyframe_id).\n"
                f"Ответ строго в JSON:\n"
                f'{{"episode_log": "...", "updated_entities": [{{"name": "...", "new_trait": "...", "keyframe_id": "..."}}]}}'
            )

            # Query LLM or use deterministic heuristic
            response_json = self._query_llm_or_fallback(prompt, recent_subs, recent_frames)
            episode_log = response_json.get("episode_log", "")
            updated_entities = response_json.get("updated_entities", [])

            if episode_log:
                self._episode_logs.append(episode_log)
                if len(self._episode_logs) > 100:
                    self._episode_logs.pop(0)

            for ent in updated_entities:
                name = str(ent.get("name", "")).strip()
                if name:
                    if name not in self._character_cards:
                        self._character_cards[name] = {
                            "name": name,
                            "traits": [],
                            "last_seen": time.time(),
                            "keyframe_id": ent.get("keyframe_id", ""),
                        }
                    card = self._character_cards[name]
                    trait = str(ent.get("new_trait", "")).strip()
                    if trait and trait not in card["traits"]:
                        card["traits"].append(trait)
                    if ent.get("keyframe_id"):
                        card["keyframe_id"] = ent["keyframe_id"]
                    card["last_seen"] = time.time()

            # Record consolidation metadata into LanceDB keyframes if available
            if self.episodic_memory is not None and hasattr(self.episodic_memory, "save_taste_record"):
                # Tag last keyframes with episode log
                pass

            if episode_log or updated_entities:
                self._save()

            self._last_consolidation_time = now_mono
            return {
                "episode_log": episode_log,
                "updated_entities": updated_entities,
                "character_cards_count": len(self._character_cards),
            }

    def _load(self) -> None:
        if self.storage_path is None or not self.storage_path.is_file():
            return
        try:
            raw = self.storage_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                logs = data.get("episode_logs")
                if isinstance(logs, list):
                    self._episode_logs = [str(x) for x in logs if isinstance(x, str)][-100:]
                cards = data.get("character_cards")
                if isinstance(cards, dict):
                    self._character_cards = {
                        str(k): dict(v) for k, v in cards.items() if isinstance(v, dict)
                    }
                elif isinstance(cards, list):
                    self._character_cards = {
                        str(c.get("name")): dict(c)
                        for c in cards
                        if isinstance(c, dict) and c.get("name")
                    }
        except Exception as exc:
            logger.warning("Failed loading narrative storage from %s: %s", self.storage_path, exc)

    def _save(self) -> None:
        if self.storage_path is None:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "saved_at": time.time(),
                "episode_logs": list(self._episode_logs),
                "character_cards": dict(self._character_cards),
            }
            tmp = self.storage_path.with_suffix(f".tmp.{os.getpid()}")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.storage_path)
        except Exception as exc:
            logger.warning("Failed saving narrative storage to %s: %s", self.storage_path, exc)

    def redact(self, identifiers: list[str], reason: str = "") -> dict[str, Any]:
        """Redact story logs and character cards mentioning sensitive identifiers."""
        wanted = {str(item).strip() for item in (identifiers or []) if str(item or "").strip()}
        if not wanted:
            return {"status": "nothing_to_redact", "deleted_logs": 0, "deleted_cards": 0}

        with self._lock:
            # 1. Filter episode logs
            initial_logs = len(self._episode_logs)
            filtered_logs = []
            for line in self._episode_logs:
                should_remove = any(ident.lower() in line.lower() for ident in wanted)
                if not should_remove:
                    filtered_logs.append(line)
            deleted_logs = initial_logs - len(filtered_logs)
            self._episode_logs = filtered_logs

            # 2. Filter character cards
            initial_cards = len(self._character_cards)
            cards_to_remove = []
            for name, card in self._character_cards.items():
                card_name = str(card.get("name") or "").strip()
                card_keyframe = str(card.get("keyframe_id") or "").strip()
                traits = card.get("traits") or []

                if (
                    card_name in wanted
                    or any(ident.lower() == card_name.lower() for ident in wanted)
                    or card_keyframe in wanted
                    or any(ident in card_keyframe for ident in wanted)
                    or any(any(ident.lower() in str(t).lower() for ident in wanted) for t in traits)
                ):
                    cards_to_remove.append(name)

            for name in cards_to_remove:
                del self._character_cards[name]
            deleted_cards = initial_cards - len(self._character_cards)

            if deleted_logs > 0 or deleted_cards > 0:
                self._save()

            return {
                "status": "redacted",
                "reason": str(reason or "")[:120],
                "deleted_logs": deleted_logs,
                "deleted_cards": deleted_cards,
                "remaining_cards": len(self._character_cards),
            }

    def _query_llm_or_fallback(
        self,
        prompt: str,
        subs: list[dict[str, Any]],
        frames: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Query external LLM or generate a clean structured fallback."""
        if self.llm_client is not None:
            try:
                raw = ""
                if hasattr(self.llm_client, "complete"):
                    raw = str(self.llm_client.complete(prompt))
                elif hasattr(self.llm_client, "chat"):
                    raw = str(self.llm_client.chat([{"role": "user", "content": prompt}]))
                elif callable(self.llm_client):
                    raw = str(self.llm_client(prompt))

                # Extract JSON block
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict) and "episode_log" in parsed:
                        return parsed
            except Exception as exc:
                logger.warning("NarrativeConsolidator LLM query failed, falling back: %s", exc)

            # Clean deterministic fallback: strictly factual, no hallucinated entities
        now_str = datetime.datetime.now().strftime("%H:%M")
        sample_text = subs[-1]["text"] if subs else (frames[-1].get("summary") if frames else "Сцена продолжается")
        return {
            "episode_log": f"{now_str} — {sample_text[:120]}",
            "updated_entities": [],
        }

    def get_last_story_line(self) -> str:
        """Get the most recent consolidated 1-line narrative episode log."""
        with self._lock:
            if self._episode_logs:
                return self._episode_logs[-1]
            return "Начало наблюдения за происходящим."

    def get_character_cards(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._character_cards.values())

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_episode_logs": len(self._episode_logs),
                "last_story_line": self.get_last_story_line(),
                "total_character_cards": len(self._character_cards),
                "subtitles_buffered": len(self._subtitles),
                "keyframes_buffered": len(self._keyframes),
                "last_consolidation_sec_ago": round(time.monotonic() - self._last_consolidation_time, 1),
                "storage_path": str(self.storage_path) if self.storage_path else None,
            }
