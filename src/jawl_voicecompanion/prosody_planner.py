"""LLM prosody planner: per-sentence emotion envelopes for the TTS lane.

The planner runs on the local OpenAI-compatible provider after the first
sentence has already been submitted for synthesis, so first-audio latency is
never blocked by it. Every envelope is clamped to the worker bounds; any
planner failure degrades to neutral prosody (fail-soft by construction).
"""

from __future__ import annotations

import json
import re
from typing import Any

from urllib.request import Request, urlopen

# Worker-side bounds (scripts/teratts_server.py)
PITCH_BOUNDS = (-6.0, 6.0)
RANGE_BOUNDS = (0.4, 2.2)
ENERGY_BOUNDS = (0.5, 1.5)
SPEED_BOUNDS = (0.5, 2.0)

# Perceptual envelopes tuned on the world2 listening bench (2026-09-10).
EMOTION_PRESETS: dict[str, dict[str, float]] = {
    "neutral": {"pitch": 0.0, "f0_range": 1.0, "energy": 1.0, "speed": 1.0},
    "happy": {"pitch": 2.5, "f0_range": 1.6, "energy": 1.2, "speed": 1.08},
    "excited": {"pitch": 3.5, "f0_range": 1.9, "energy": 1.25, "speed": 1.12},
    "angry": {"pitch": 1.5, "f0_range": 1.8, "energy": 1.45, "speed": 1.08},
    "sad": {"pitch": -2.5, "f0_range": 0.55, "energy": 0.72, "speed": 0.88},
    "calm": {"pitch": -1.0, "f0_range": 0.7, "energy": 0.85, "speed": 0.92},
    "curious": {"pitch": 1.5, "f0_range": 1.4, "energy": 1.05, "speed": 1.0},
    "serious": {"pitch": -0.5, "f0_range": 0.8, "energy": 1.0, "speed": 0.96},
}


def _clamp(value: Any, bounds: tuple[float, float], default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    low, high = bounds
    return max(low, min(high, float(value)))


class ProsodyPlanner:
    """Bounded, fail-soft per-sentence emotion annotation."""

    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        api_key: str = "local-loopback",
        timeout_seconds: float = 6.0,
        opener: Any = urlopen,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.model = str(model)
        self.api_key = str(api_key)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 15.0))
        self._opener = opener

    def plan(self, sentences: list[str]) -> list[dict[str, float]] | None:
        """Return one bounded envelope per sentence, or None on any failure."""
        if not sentences:
            return None
        try:
            raw = self._complete(self._prompt(sentences))
            values = self._parse(raw, len(sentences))
        except Exception:
            return None
        return values

    def _prompt(self, sentences: list[str]) -> str:
        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
        return (
            "Разметь эмоцию каждой реплики для озвучки. Доступные эмоции: "
            "neutral, happy, excited, angry, sad, calm, curious, serious.\n"
            f"Ответь ТОЛЬКО JSON-массивом длиной {len(sentences)}: "
            '[{"emotion": "..."}] без пояснений.\nРеплики:\n' + numbered
        )

    def _complete(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 40 * len(json.dumps(EMOTION_PRESETS)) // 40 + 64,
            "stream": False,
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with self._opener(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"])

    def _parse(self, raw: str, expected: int) -> list[dict[str, float]]:
        start = raw.find("[")
        end = raw.rfind("]")
        if start < 0 or end <= start:
            raise ValueError("planner response has no JSON array")
        items = json.loads(raw[start:end + 1])
        if not isinstance(items, list) or not items:
            raise ValueError("planner response is not a non-empty array")
        # Tolerant alignment: pad/truncate to the sentence count so a model
        # that miscounts still degrades to neutral rather than failing.
        neutral = dict(EMOTION_PRESETS["neutral"])
        while len(items) < expected:
            items.append(neutral)
        items = items[:expected]
        values: list[dict[str, float]] = []
        for item in items:
            emotion_id = ""
            if isinstance(item, dict):
                emotion_id = str(item.get("emotion", "")).casefold().strip()
            preset = dict(EMOTION_PRESETS.get(emotion_id, EMOTION_PRESETS["neutral"]))
            if isinstance(item, dict):
                if "pitch" in item:
                    preset["pitch"] = _clamp(item.get("pitch"), PITCH_BOUNDS, preset["pitch"])
                if "f0_range" in item:
                    preset["f0_range"] = _clamp(item.get("f0_range"), RANGE_BOUNDS, preset["f0_range"])
                if "energy" in item:
                    preset["energy"] = _clamp(item.get("energy"), ENERGY_BOUNDS, preset["energy"])
                if "speed" in item:
                    preset["speed"] = _clamp(item.get("speed"), SPEED_BOUNDS, preset["speed"])
            values.append(preset)
        return values


__all__ = ["ProsodyPlanner", "EMOTION_PRESETS", "_clamp"]
