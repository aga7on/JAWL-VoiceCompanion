# Event Contract

All events are JSON objects with this base shape:

```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "session_id": "session-id",
  "created_at": "2026-08-31T12:00:00+03:00",
  "source": "voice_gateway",
  "type": "USER_FINAL",
  "priority": 0,
  "payload": {}
}
```

## Core event types

### `USER_PARTIAL`

Intermediate ASR text. It must not launch a full JAWL turn.

```json
{
  "text": "давай посмотрим на…",
  "is_final": false,
  "confidence": 0.84
}
```

### `USER_FINAL`

Final user utterance. This is the normal highest-priority conversational
event.

```json
{
  "text": "Давай посмотрим на ошибку в редакторе.",
  "is_final": true,
  "emotion": {
    "valence": -0.1,
    "arousal": 0.3,
    "label": "focused",
    "confidence": 0.72
  }
}
```

### `BARGE_IN`

The user speaks while output is active.

```json
{
  "text": "Нет, другой файл.",
  "category": "amend",
  "reason": "matched_amend_pattern"
}
```

### `VOICE_TURN`

The VoiceMem gateway's correlated result. It may include transcript, affect,
speaker and retrieved context. JAWL should consume the final event rather than
trusting uncorrelated partial messages.

### `SCREEN_DELTA`

Bounded description of a meaningful screen change. Raw images should not be
embedded in durable event logs.

```json
{
  "app": "Visual Studio Code",
  "window": "main.py",
  "summary": "В терминале появилась ошибка импорта.",
  "significance": 4,
  "captured_at": "2026-08-31T12:01:00+03:00"
}
```

### `SPEAK_INTENT`

An Attention/Presence proposal. JAWL must still apply DND, cooldown,
relevance, priority and personality before speaking.

```json
{
  "topic": "user_stuck",
  "reason": "Пользователь долго работает с одной ошибкой.",
  "priority": "low",
  "expires_at": "2026-08-31T12:05:00+03:00"
}
```

### `TOOL_APPROVAL`

Approval request or decision. Approval state is not durable conversational
memory unless explicitly recorded as such.

### `DND_CHANGED`

Updates quiet hours, manual DND, screen permission or proactive budget.

## Rules

- Events must be idempotent or carry a deduplication key.
- Partial events may be dropped; final events may not be silently dropped.
- Low-value screen events are coalesced.
- A newer user event supersedes lower-priority proactive/background work.
- Event payloads are untrusted data and must be framed as data in prompts.
