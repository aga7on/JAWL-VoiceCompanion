# Ambient audio claim guard (2026-10-24)

The ambient path now abstains on unsupported music details at the persistence boundary:

- `unknown`, `sound`, and `speech` descriptions are normalized to neutral text and lose music/SFX tags and mood. `mixed` is rejected because there is no independent overlap detector.
- EG2's speech/music decisions both come from the same heuristic DSP features. A DSP speech flag without transcript now abstains as unknown; only nonempty transcript text confirms speech. When only the existing music heuristic fires, it emits `audio_kind=sound` and the allowlisted text “Possible rhythmic sound; music is not independently verified” with zero confidence and no tags/mood/BPM/key. Ambient memory preserves that exact cue only with empty tags and zero confidence; downstream composition therefore cannot interpret it as confirmed music.
- The bridge passes the final transcript for the current segment into description handling. If ASR found speech, music/mixed/speech captions are stored only as speech with no tags or mood; the text states that background music was not independently confirmed.
- `AmbientMemoryBuffer.ingest` applies the same sanitation to direct ambient audio events, including `mixed` and invalid audio kinds.
- `PerceptionFusion.observe_displays` and the on-demand display composition path classify audio separately from the screen, then fuse only the safe projected result. `StreamingPerception` uses the transcript or the same safe projection; unclassified/silence audio is omitted. EG2 cosine similarity is no longer exposed as claim confidence on these routes.

The same-PCM replay exposed repeated unsupported labels on speech, generated noise, and digital silence. The focused tests cover the unknown abstention, EG2 speech/unknown sanitation, and transcript-vs-music conflict. They do not establish music-classification accuracy.

Brain-facing enrichment now adds an explicit Russian instruction when fresh
audio contains `candidate_tags_calibrated=false`: treat those tags as unverified
hypotheses, do not state genre/instrument/mood as established fact, and hedge
if the user asks. Focused contract tests verify that the instruction travels
only with fresh, uncalibrated candidates and is absent for calibrated, missing,
or stale tags. This checks prompt construction only; no live Hikari response
has verified model compliance.

Independent speech+music recognition remains unavailable in this path. The conservative guard therefore loses genuine overlap details when speech is present. Restore overlap claims only after an independent music detector is evaluated on source-disjoint speech+music and matched speech-only/noise controls. The existing EG2 rhythm heuristic is not calibrated; “possible rhythmic sound” is a cue, not an established music fact.

Deferred: `SensoryIngestor._music` persists the separate `music_state` sidecar emitted by `scripts/sensory_worker.py` from librosa beat/key analysis. It has no independent music-vs-speech/noise reject gate and remains a potential false-claim route if that optional sidecar is enabled. It was not changed in this narrow patch.

Verification after the postguard A16 correction: 70 focused tests passed (`test_audio_understanding`, `test_ambient_audio`, `test_ambient_memory`, `test_perception_fusion`, `test_streaming_perception`, `test_eg2_describer`, excluding a live-display assertion); `py_compile` passed. The unfiltered EG2 test module had one unrelated live-display failure: OCR count was 3 where the fixture test expected more than 5.
