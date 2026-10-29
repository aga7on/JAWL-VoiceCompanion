# VA audio-channel handoff — 2026-10-29

## Finding

`PerceptionFusion` already retained `audio_description` and `audio_candidates`,
and included them in its composed sensor snapshot. `perception_packet.make_packet`
iterated a fixed allowlist of channel labels that omitted both keys. These
semantic audio outputs could therefore be silently dropped before Companion
attached the packet to a brain-bound turn, while ASR, YAMNet music presence, and
sound-event hypotheses used recognized keys and survived.

## Change and evidence

- Added explicit packet labels for `audio_description` and `audio_candidates`.
- Added a packet regression covering simultaneous screen, OCR, ASR, audio
  caption, gated audio candidates, YAMNet music presence, and sound-event
  hypotheses.
- Extended `CompanionServer.enrich_turn_text` coverage to verify those channels
  survive actual user-turn enrichment and are rendered for the brain.
- `test_perception_packet.py`: 9/9 passed.
- `test_web.py`: 85/85 passed, including the combined enrichment path.
- `test_native_jawl_turn_context.py`: 17/17 passed; the native
  context receives all seven channels in its separate `PERCEPTION / VA` section
  while the original user message is kept clean.
- Adjacent freshness/safety gates: fusion 23/23, ambient audio 32/32, and
  YAMNet soundscape 10/10 passed.

This closes the code-level omission at the VA handoff. A live session still needs
to show real audio descriptions arriving and the active brain using them; these
tests do not establish descriptor accuracy or live runtime quality.
