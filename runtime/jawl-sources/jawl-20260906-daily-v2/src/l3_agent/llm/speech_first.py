"""Speech-first extraction from a partially streamed JAWL JSON envelope (D2-01).

The pinned JAWL brain answers with one JSON envelope::

    {"observation": "...", "reasoning": "...",
     "actions": [{"tool_name": "HostTerminalMessages.send_message_to_terminal",
                  "parameters": {"text": "Привет! Как дела?"}}]}

Playback used to start only after the closing brace, so the voice lane paid
for the whole generation before the first sound.  This module reads the *same*
streamed bytes and answers one question: which part of the reply is already
safe to speak?

Two rules keep it honest:

* only the terminal-message action's ``text`` argument is ever a candidate —
  ``observation`` / ``reasoning`` stay private and are never spoken;
* a chunk is spoken only when it ends on a real sentence boundary, so the
  voice never stutters on a half-written word.

The module is pure (no IO, no model) so it can be tested against truncated
JSON buffers byte by byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "TERMINAL_TOOL_NAMES",
    "SpeechChunk",
    "SpeechFirstGate",
    "extract_speech_text",
    "first_speakable_chunk",
    "looks_like_reply_action",
]

TERMINAL_TOOL_NAMES: tuple[str, ...] = (
    "HostTerminalMessages.send_message_to_terminal",
)

_TEXT_KEY_RE = re.compile(r'"text"\s*:\s*"')
_TOOL_NAME_RE = re.compile(r'"(?:tool_name|name)"\s*:\s*"([^"\\]{1,120})"')
_PARAMETERS_RE = re.compile(r'"parameters"\s*:\s*\{')
_SENTENCE_END_RE = re.compile(r"[.!?…]+(?=\s|$)")
_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")

# Abbreviations that end with a dot but do not end a sentence.
_FALSE_BOUNDARIES = (
    "т.е", "т.д", "т.п", "и.о", "и.т.д", "др", "г.", "гг", "с.", "руб",
    "коп", "мин", "сек", "стр", "рис", "табл", "см", "проф", "доц",
)


@dataclass
class SpeechChunk:
    """One speakable slice of the reply plus the bookkeeping around it."""

    text: str
    start: int
    end: int
    complete: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "complete": self.complete,
        }


def looks_like_reply_action(buffer: str) -> bool:
    """True when the buffer already names a terminal-message action."""
    for name in _TOOL_NAME_RE.findall(buffer or ""):
        if name in TERMINAL_TOOL_NAMES:
            return True
    return False


def _decode_json_string(buffer: str, quote_index: int) -> tuple[str, bool]:
    """Decode one JSON string that starts at ``quote_index``.

    Returns ``(value, complete)``.  A truncated tail (half an escape, a
    half-written code point) is dropped, so the next streamed chunk can
    deliver it again.
    """
    if quote_index >= len(buffer) or buffer[quote_index] != '"':
        return "", False
    simple = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    out: list[str] = []
    index = quote_index + 1
    while index < len(buffer):
        char = buffer[index]
        if char == "\\":
            if index + 1 >= len(buffer):
                break
            nxt = buffer[index + 1]
            if nxt == "u":
                hexpart = buffer[index + 2 : index + 6]
                if len(hexpart) < 4:
                    break
                try:
                    out.append(chr(int(hexpart, 16)))
                except ValueError:
                    break
                index += 6
                continue
            if nxt not in simple:
                break
            out.append(simple[nxt])
            index += 2
            continue
        if char == '"':
            return "".join(out), True
        out.append(char)
        index += 1
    return "".join(out), False


def _text_candidates(buffer: str) -> list[tuple[int, str, bool]]:
    """Return every ``"text": "..."`` value in the buffer with its position."""
    candidates: list[tuple[int, str, bool]] = []
    for match in _TEXT_KEY_RE.finditer(buffer):
        quote_index = match.end() - 1
        value, complete = _decode_json_string(buffer, quote_index)
        candidates.append((match.start(), value, complete))
    return candidates


def extract_speech_text(buffer: str) -> tuple[str, bool, bool]:
    """Extract the terminal reply text from a partial envelope.

    Returns ``(text, complete, is_reply)``.  ``is_reply`` is False when the
    buffer does not yet prove that the ``text`` field belongs to the
    terminal-message action — in that case the caller must wait instead of
    speaking private reasoning.
    """
    raw = buffer or ""
    if not raw:
        return "", False, False

    candidates = _text_candidates(raw)
    if not candidates:
        return "", False, False

    # Preferred: a text key that follows a terminal-message tool name.
    tool_matches = list(_TOOL_NAME_RE.finditer(raw))
    for tool in reversed(tool_matches):
        if tool.group(1) not in TERMINAL_TOOL_NAMES:
            continue
        after = [c for c in candidates if c[0] > tool.start()]
        if after:
            _, value, complete = after[0]
            return value, complete, True

    # Fallback: the first text key inside a "parameters" object.
    for params in _PARAMETERS_RE.finditer(raw):
        after = [c for c in candidates if c[0] > params.start()]
        if after:
            _, value, complete = after[0]
            return value, complete, True

    return "", False, False


def _is_false_boundary(text: str, boundary_end: int) -> bool:
    """Reject abbreviations like "т.е." that look like sentence ends."""
    tail = text[:boundary_end].rstrip()
    if not tail:
        return True
    last = tail.rsplit(" ", 1)[-1].casefold().rstrip(".")
    if not last:
        return True
    if last in {item.rstrip(".") for item in _FALSE_BOUNDARIES}:
        return True
    # A single capital letter before the dot is an initial, not an ending.
    if len(last) == 1 and last.isalpha():
        return True
    return False


def first_speakable_chunk(
    text: str,
    *,
    min_chars: int = 3,
    min_words: int = 1,
    long_clause_chars: int = 120,
) -> SpeechChunk | None:
    """Return the first part of ``text`` that is safe to speak now.

    A chunk is returned when the text reaches a genuine sentence boundary
    (``.``/``!``/``?``/``…`` followed by a space or the end) or when a long
    clause has been streamed with a completed last word.
    """
    raw = str(text or "")
    if not raw.strip():
        return None

    for match in _SENTENCE_END_RE.finditer(raw):
        end = match.end()
        if _is_false_boundary(raw, end):
            continue
        chunk = raw[:end].strip()
        if len(chunk) < max(1, int(min_chars)):
            continue
        if len(_WORD_RE.findall(chunk)) < max(1, int(min_words)):
            continue
        # ``end`` is the raw offset of the boundary, not the stripped length:
        # the caller cuts the original text by it.
        return SpeechChunk(text=chunk, start=0, end=end, complete=True)

    # Long mid-sentence clause: speak it when the last word is finished.
    if long_clause_chars and len(raw) >= int(long_clause_chars):
        cut = raw.rfind(" ")
        while cut > int(long_clause_chars) // 2 and cut > 0:
            head = raw[:cut]
            if len(_WORD_RE.findall(head)) >= max(1, int(min_words)):
                return SpeechChunk(text=head.strip(), start=0, end=cut, complete=False)
            cut = raw.rfind(" ", 0, cut)
    return None


@dataclass
class SpeechFirstGate:
    """Stateful speech-first gate over one streamed reply.

    Feed the raw streamed bytes; the gate returns the next speakable chunk as
    soon as it is safe.  :meth:`finalize` returns the part of the authoritative
    final text that was never spoken, so nothing is lost and nothing is said
    twice.
    """

    min_chars: int = 3
    min_words: int = 1
    long_clause_chars: int = 120
    _buffer: str = field(default="", init=False, repr=False)
    _extracted: str = field(default="", init=False, repr=False)
    _spoken_chars: int = field(default=0, init=False, repr=False)

    def feed(self, delta: str) -> str | None:
        """Consume a streamed fragment and return text ready to speak."""
        if delta:
            self._buffer += delta
        text, _complete, is_reply = extract_speech_text(self._buffer)
        if not is_reply or not text:
            return None
        self._extracted = text
        window = text[self._spoken_chars :]
        chunk = first_speakable_chunk(
            window,
            min_chars=self.min_chars,
            min_words=self.min_words,
            long_clause_chars=self.long_clause_chars,
        )
        if chunk is None:
            return None
        end = self._spoken_chars + chunk.end
        if end <= self._spoken_chars:
            return None
        # The spoken slice keeps its original spacing so that the spoken text
        # plus the final tail reconstructs the reply byte for byte.
        piece = text[self._spoken_chars : end]
        self._spoken_chars = end
        return piece if piece.strip() else None

    def finalize(self, final_text: str) -> tuple[str, bool]:
        """Return ``(unsspoken_tail, mismatch)`` for the authoritative text."""
        authoritative = str(final_text or "")
        spoken_prefix = self._extracted[: self._spoken_chars]
        if not spoken_prefix:
            return authoritative, False
        if authoritative.startswith(spoken_prefix):
            return authoritative[self._spoken_chars :], False
        # The stream diverged from the final envelope: the spoken words can no
        # longer be trusted, so the caller must decide what to do.
        return authoritative, True

    def flush(self) -> str:
        """Return the remaining extracted text when the stream just ended.

        Used when the authoritative final text is not available (the brain hook
        sees only the streamed envelope): the already-extracted reply is the
        best truth we have.
        """
        tail = self._extracted[self._spoken_chars :].strip()
        self._spoken_chars = len(self._extracted)
        return tail

    @property
    def spoken_chars(self) -> int:
        return self._spoken_chars

    @property
    def pending_text(self) -> str:
        """Part of the extracted reply that was not spoken yet."""
        return self._extracted[self._spoken_chars :]

    def state(self) -> dict[str, object]:
        return {
            "buffered_chars": len(self._buffer),
            "extracted_chars": len(self._extracted),
            "spoken_chars": self._spoken_chars,
            "reply_detected": looks_like_reply_action(self._buffer),
        }
