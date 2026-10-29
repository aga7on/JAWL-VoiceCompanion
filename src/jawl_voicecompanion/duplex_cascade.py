"""Deterministic micro-turn heuristic inspired by DuplexCascade.

Exposes six local control labels for the Russian JAWL Companion pipeline.
This is not the paper's trained controller or a validated VAD-free model:

* ``<|no voice|>`` — user is silent and no unfinished utterance is pending.
* ``<|user is talking|>`` — user is actively speaking a multi-word turn.
* ``<|user is thinking|>`` — user paused mid-sentence on a conjunction,
  preposition, filler ("э-э", "а-а", "ну", "как бы", "чтобы", "который...")
  or trailing hesitation; hold the turn open instead of cutting off early.
* ``<|user backchannel|>`` — while the assistant is speaking, the user emitted
  a brief acknowledgement ("угу", "ага", "да", "ясно", "понял", "ого", "круто")
  or short non-verbal reaction; assistant MUST NOT stop speaking (triggers a
  subtle avatar nod instead).
* ``<|user interruption|>`` — while the assistant is speaking, the user issued
  an explicit stop/redirect ("стой", "подожди", "стоп", "хватит", "слушай",
  "нет") or a substantive multi-word statement; immediately reset TTS.
* ``<|user finish talking|>`` — the user's utterance is semantically complete;
  commit the turn immediately with a short silence window (~300 ms) instead of
  waiting for a long static VAD timeout.

When ``EmbeddingGemma 2`` ONNX weights are available in
``runtime/models/embeddinggemma-2-onnx``, the controller also computes fast
semantic similarity against precomputed Russian prototype banks as diagnostics.
These optional scores do not change the rule-based decision. Latency and
recognition quality require separate measurements on the selected hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Any


TOKEN_NO_VOICE = "<|no voice|>"
TOKEN_USER_TALKING = "<|user is talking|>"
TOKEN_USER_THINKING = "<|user is thinking|>"
TOKEN_USER_FINISH = "<|user finish talking|>"
TOKEN_USER_INTERRUPTION = "<|user interruption|>"
TOKEN_USER_BACKCHANNEL = "<|user backchannel|>"

SPECIAL_TOKENS = (
    TOKEN_NO_VOICE,
    TOKEN_USER_TALKING,
    TOKEN_USER_FINISH,
    TOKEN_USER_THINKING,
    TOKEN_USER_INTERRUPTION,
    TOKEN_USER_BACKCHANNEL,
)

_WORD_RE = re.compile(r"[а-яёa-z0-9-]+", re.IGNORECASE)

# Russian backchannel tokens (short acknowledgements during assistant speech)
_RU_BACKCHANNEL_WORDS = frozenset({
    "угу", "ага", "да", "ну да", "ясно", "понял", "понятно", "окей", "ок",
    "хорошо", "круто", "ого", "вау", "классно", "точно", "верно", "ладно",
    "мгм", "хм", "ах", "ох", "ха", "хех", "прикольно", "ништяк", "супер",
})

# Explicit Russian interruption / takeover markers
_RU_INTERRUPT_WORDS = frozenset({
    "стоп", "стой", "подожди", "погоди", "хватит", "тихо", "замолчи",
    "слушай", "послушай", "нет", "не надо", "остановись", "перестань",
    "лучше", "давай", "вопрос", "скажи", "расскажи", "почему", "зачем", "как",
})

# Trailing Russian connectors / fillers indicating an unfinished thought
_RU_THINKING_TRAILERS = frozenset({
    "э", "ээ", "эээ", "э-э", "э-э-э", "а", "аа", "ааа", "а-а", "а-а-а",
    "м", "мм", "м-м", "ну", "вот", "типа", "короче", "значит", "вроде",
    "и", "или", "но", "что", "чтобы", "потому", "если", "когда",
    "который", "которая", "которые", "которое", "как", "где", "куда",
    "откуда", "в", "на", "с", "со", "к", "по", "о", "об", "про", "для",
    "без", "из", "за", "над", "под", "перед", "через", "хотел", "хочу",
    "думаю", "решил", "давай", "может", "например", "итак",
})

_RU_THINKING_BIGRAMS = frozenset({
    "как бы", "то есть", "потому что", "так что", "для того", "в общем",
    "короче говоря", "честно говоря", "я хотел", "я хочу", "давай мы",
    "а если", "ну вот",
})


def is_user_backchannel(text: str) -> bool:
    """Recognize only explicit brief acknowledgements, never questions or arbitrary words."""
    raw = str(text or "").strip()
    if raw.endswith(("?", "？")):
        return False
    words = DuplexCascadeArbiter._normalize_words(raw)
    return bool(words) and len(words) <= 2 and (
        " ".join(words) in _RU_BACKCHANNEL_WORDS
        or all(word in _RU_BACKCHANNEL_WORDS for word in words)
    )


@dataclass(frozen=True)
class MicroTurnDecision:
    """Decision emitted on a DuplexCascade micro-turn tick."""

    token: str
    action: str  # "continue" | "hold_turn" | "commit_turn" | "cancel_tts" | "ignore_backchannel"
    recommended_silence_ms: int
    confidence: float
    reason: str
    avatar_gesture: str | None = None
    eg2_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "action": self.action,
            "recommended_silence_ms": self.recommended_silence_ms,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "avatar_gesture": self.avatar_gesture,
            "eg2_score": round(self.eg2_score, 4) if self.eg2_score is not None else None,
        }


class EmbeddingGemmaTurnScorer:
    """Optional CPU ONNX scorer using EmbeddingGemma 2 (768d Matryoshka space)."""

    def __init__(self, model_root: Path) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self.tokenizer = Tokenizer.from_file(str(model_root / "tokenizer.json"))
        self.session = ort.InferenceSession(
            str(model_root / "onnx" / "model_q4.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self._empty = np.zeros((0, 512), dtype=np.float32)
        self._prototypes = {
            TOKEN_USER_BACKCHANNEL: self._embed(
                "title: none | text: Короткое поддакивание собеседника без вопроса: угу, ага, понятно, ясно, круто, ого"
            ),
            TOKEN_USER_INTERRUPTION: self._embed(
                "title: none | text: Перебивание и смена темы: стой, подожди, хватит, слушай сюда, у меня другой вопрос, давай лучше"
            ),
            TOKEN_USER_THINKING: self._embed(
                "title: none | text: Незаконченная оборванная на полуслове мысль с паузой размышления: я хотел чтобы мы, ну как бы, э-э"
            ),
            TOKEN_USER_FINISH: self._embed(
                "title: none | text: Полностью законченный вопрос или завершённое предложение пользователя"
            ),
        }

    def _embed(self, text: str):
        np = self._np
        ids = np.array([[2] + self.tokenizer.encode(text).ids + [1]], dtype=np.int64)
        mask = np.ones_like(ids)
        vec = self.session.run(
            ["sentence_embedding"],
            {
                "input_ids": ids,
                "attention_mask": mask,
                "image_features": self._empty,
                "video_features": self._empty,
                "audio_features": self._empty,
            },
        )[0][0]
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm

    def score(self, text: str) -> dict[str, float]:
        np = self._np
        query = self._embed(f"task: classification | query: {text}")
        return {
            token: float(np.dot(query, proto))
            for token, proto in self._prototypes.items()
        }


class DuplexCascadeArbiter:
    """Bounded text/acoustic heuristic; requires upstream speech observations."""

    def __init__(
        self,
        *,
        eg2_model_root: Path | None = None,
        fast_finish_silence_ms: int = 380,
        normal_silence_ms: int = 850,
        thinking_silence_ms: int = 2200,
    ) -> None:
        self.fast_finish_silence_ms = int(fast_finish_silence_ms)
        self.normal_silence_ms = int(normal_silence_ms)
        self.thinking_silence_ms = int(thinking_silence_ms)
        self._scorer: EmbeddingGemmaTurnScorer | None = None
        if eg2_model_root is not None and (eg2_model_root / "onnx" / "model_q4.onnx").is_file():
            try:
                self._scorer = EmbeddingGemmaTurnScorer(eg2_model_root)
            except Exception:
                self._scorer = None

    @staticmethod
    def _normalize_words(text: str) -> list[str]:
        cleaned = text.lower().replace("ё", "е")
        return [w.strip("-") for w in _WORD_RE.findall(cleaned) if w.strip("-")]

    def evaluate_micro_turn(
        self,
        transcript: str,
        *,
        assistant_speaking: bool = False,
        silence_elapsed_ms: float = 0.0,
        speech_duration_ms: float = 0.0,
        rms_peak: float = 0.0,
    ) -> MicroTurnDecision:
        """Classify the current micro-turn state and return the control token."""
        raw = (transcript or "").strip()
        words = self._normalize_words(raw)

        # 1. No speech detected at all
        if not words and rms_peak < 0.015:
            return MicroTurnDecision(
                token=TOKEN_NO_VOICE,
                action="continue",
                recommended_silence_ms=self.normal_silence_ms,
                confidence=0.99,
                reason="no_voice_activity",
            )

        # Optional EmbeddingGemma 2 semantic scores (~13 ms on CPU)
        eg2_scores = self._scorer.score(raw) if (self._scorer and raw) else {}

        # 2. Assistant is currently speaking -> decide Backchannel vs Interruption!
        if assistant_speaking:
            has_interrupt_word = any(w in _RU_INTERRUPT_WORDS for w in words)
            is_short_backchannel = (
                is_user_backchannel(raw)
                or (not words and speech_duration_ms < 450)
            )
            if is_short_backchannel and not has_interrupt_word:
                return MicroTurnDecision(
                    token=TOKEN_USER_BACKCHANNEL,
                    action="ignore_backchannel",
                    recommended_silence_ms=self.normal_silence_ms,
                    confidence=0.94,
                    reason="short_backchannel_while_assistant_speaking",
                    avatar_gesture="nod",
                    eg2_score=eg2_scores.get(TOKEN_USER_BACKCHANNEL),
                )
            if has_interrupt_word or len(words) >= 2 or speech_duration_ms >= 550:
                return MicroTurnDecision(
                    token=TOKEN_USER_INTERRUPTION,
                    action="cancel_tts",
                    recommended_silence_ms=self.normal_silence_ms,
                    confidence=0.96,
                    reason="substantive_user_interruption",
                    eg2_score=eg2_scores.get(TOKEN_USER_INTERRUPTION),
                )
            # Very brief ambiguous sound (<450ms, 1 word): hold before killing TTS
            return MicroTurnDecision(
                token=TOKEN_USER_BACKCHANNEL,
                action="ignore_backchannel",
                recommended_silence_ms=self.normal_silence_ms,
                confidence=0.75,
                reason="brief_sound_held_against_false_bargein",
                avatar_gesture="nod",
                eg2_score=eg2_scores.get(TOKEN_USER_BACKCHANNEL),
            )

        # 3. User is speaking (assistant is silent) -> Talking vs Thinking vs Finish
        if not words:
            return MicroTurnDecision(
                token=TOKEN_USER_TALKING,
                action="hold_turn",
                recommended_silence_ms=self.normal_silence_ms,
                confidence=0.7,
                reason="acoustic_activity_awaiting_words",
            )

        last_word = words[-1]
        last_two = " ".join(words[-2:]) if len(words) >= 2 else ""
        ends_with_ellipsis = raw.endswith("...") or raw.endswith("…") or raw.endswith(",") or raw.endswith("-")
        ends_with_question_or_bang = raw.endswith("?") or raw.endswith("!")
        has_thinking_trailer = (
            last_word in _RU_THINKING_TRAILERS
            or last_two in _RU_THINKING_BIGRAMS
            or ends_with_ellipsis
        )

        # Check if user is actively mid-stream (silence < 220 ms)
        if silence_elapsed_ms < 220:
            return MicroTurnDecision(
                token=TOKEN_USER_TALKING,
                action="hold_turn",
                recommended_silence_ms=self.thinking_silence_ms if has_thinking_trailer else self.normal_silence_ms,
                confidence=0.92,
                reason="active_speech_stream",
            )

        # User paused on a conjunction/filler/hesitation -> <|user is thinking|>
        if has_thinking_trailer and silence_elapsed_ms < self.thinking_silence_ms:
            return MicroTurnDecision(
                token=TOKEN_USER_THINKING,
                action="hold_turn",
                recommended_silence_ms=self.thinking_silence_ms,
                confidence=0.93,
                reason=f"unfinished_syntax_trailer:{last_two or last_word}",
                eg2_score=eg2_scores.get(TOKEN_USER_THINKING),
            )

        # Semantic finish check: clear question or complete statement
        is_complete_clause = (
            ends_with_question_or_bang
            or (len(words) >= 2 and not has_thinking_trailer and (raw.endswith(".") or silence_elapsed_ms >= self.fast_finish_silence_ms))
            or silence_elapsed_ms >= self.normal_silence_ms
        )
        if is_complete_clause and silence_elapsed_ms >= self.fast_finish_silence_ms:
            return MicroTurnDecision(
                token=TOKEN_USER_FINISH,
                action="commit_turn",
                recommended_silence_ms=self.fast_finish_silence_ms,
                confidence=0.95,
                reason="semantically_complete_utterance",
                eg2_score=eg2_scores.get(TOKEN_USER_FINISH),
            )

        return MicroTurnDecision(
            token=TOKEN_USER_TALKING,
            action="hold_turn",
            recommended_silence_ms=self.fast_finish_silence_ms,
            confidence=0.80,
            reason="awaiting_micro_turn_boundary",
            eg2_score=eg2_scores.get(TOKEN_USER_FINISH),
        )


__all__ = [
    "TOKEN_NO_VOICE",
    "TOKEN_USER_TALKING",
    "TOKEN_USER_THINKING",
    "TOKEN_USER_FINISH",
    "TOKEN_USER_INTERRUPTION",
    "TOKEN_USER_BACKCHANNEL",
    "SPECIAL_TOKENS",
    "MicroTurnDecision",
    "EmbeddingGemmaTurnScorer",
    "DuplexCascadeArbiter",
    "is_user_backchannel",
]
