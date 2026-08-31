# ResponseEnvelope Contract

The cognitive core returns a versioned structured envelope. The frontend and
voice services must not infer behavior from arbitrary prose.

```json
{
  "schema_version": 1,
  "response_id": "uuid",
  "turn_id": "uuid",
  "text": "Я вижу ошибку импорта. Давай проверим путь к модулю.",
  "speak": true,
  "emotion": {
    "id": "concerned",
    "intensity": 0.55,
    "confidence": 0.82
  },
  "avatar": {
    "expression": "concerned",
    "motion": "soft_nod",
    "state": "speaking"
  },
  "voice": {
    "provider": "cozyvoice2",
    "voice_id": "main_ru",
    "rate": 1.0,
    "style": "calm and attentive"
  },
  "actions": [],
  "interruptible": true,
  "proactive": false
}
```

## Required fields

- `schema_version`;
- `response_id`;
- `turn_id`;
- `text`;
- `speak`;
- `emotion`;
- `avatar`;
- `interruptible`;
- `proactive`.

## Emotion rules

The cognitive model may produce a richer emotion taxonomy than a particular
Live2D model supports. The avatar adapter maps unsupported states to the
nearest supported expression. TTS receives a separate prosody/style mapping.

The system must never assume that an emotion label automatically changes the
voice or avatar correctly.

## Spoken text rules

- Internal reasoning is never placed in `text`.
- Control tags are removed before TTS.
- Sentence segmentation may split `text` for playback without changing the
  stored final response.
- `speak: false` still allows avatar state, subtitle or silent micro-reaction.

## Action rules

Actions are declarative requests. They do not bypass the tool policy. Any
filesystem, browser, shell, keyboard, mouse or external side effect requires
the appropriate approval and audit path.
