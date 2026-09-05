# Response envelope v1

JAWL is the canonical producer of the final response envelope. The Companion
accepts it from the native correlated Gateway and validates it before routing
text to the browser, TTS and the presentation surface.

```json
{
  "schema_version": 1,
  "response_id": "resp-123",
  "turn_id": "turn-123",
  "text": "Привет! Я на связи.",
  "speak": true,
  "emotion": {"id": "warm", "intensity": 0.7, "confidence": 0.9},
  "avatar": {"expression": "smile", "motion": "greet", "state": "speaking"},
  "voice": {"provider": "tera", "voice_id": "ru_f1", "rate": 1.0, "style": "warm"},
  "actions": [],
  "interruptible": true,
  "proactive": false
}
```

Required fields are `schema_version`, `response_id`, `turn_id`, `text`,
`speak`, `emotion`, `avatar`, `voice`, `actions`, `interruptible` and
`proactive`. IDs, text, nested strings and action arrays are bounded. Unknown
fields, malformed types, hidden reasoning, model-supplied access levels and
unbounded tool arguments are rejected.

`actions` are intent descriptions only. They do not authorize execution and
must not contain an access level. A native JAWL tool decision is executed only
through JAWL's policy, approval, audit, cancellation and emergency-stop path.

The Companion maps `voice` to the configured TTS provider and maps `emotion`
and `avatar` to bounded presentation state. The isolated `/avatar`/OBS server
receives only subtitle, expression, motion, speaking and short-lived audio
amplitude; it receives no session token, approvals, HostOS state or history.

An interrupted or cancelled turn must not be spoken as a completed response.
The final envelope is correlated with its `turn_id`; a late envelope from an
older turn is discarded.
