# Ambient secondary memory

## Decision

The idea is useful, but it must be implemented as a low-priority perception
and memory pipeline rather than as another conversational input. System audio
and screen observations can preserve context that the user never addresses
directly, while delayed analysis avoids spending VRAM or interrupting the main
conversation on every clip.

Ambient observations must not directly trigger a user turn, speech, tool call,
personality change or canonical fact write. They are evidence. JAWL remains
the owner of durable memory, final wording and action policy.

## Memory tiers

```text
T0  transient capture     RAM only; raw audio/frame while a bounded operation runs
T1  working observation   transcript/description; roughly 30-minute TTL by default
T2  ambient episode        compressed summary; configurable short retention, e.g. 7 days
T3  canonical memory       JAWL fact/episode after provenance and promotion rules
```

The exact TTLs are configuration, not a promise. T0 must be discarded after
ASR/VLM processing or cancellation. T1 and T2 must be bounded by count and
bytes. T3 must use JAWL's existing memory ownership and correction history;
the companion must not create a second durable memory database.

## Signals and separation

```text
Windows WASAPI loopback --> segmenter/ASR --\
                                              +--> delayed triage --> episode
Focused window/screen --> keyframe/VLM -----/

Microphone --> VoiceMem conversational path --> USER_PARTIAL/FINAL
```

System audio is a separate stream with its own session and correlation IDs.
It must never be sent through the microphone's conversational finalization
path. The same ASR engine may be reused if it accepts a separate stream type,
but VoiceMem's user-turn state must not be polluted by game, browser or media
audio.

The visual side should reuse the existing focused-window/change-detection
path. It should emit bounded descriptions or keyframe observations, not a
permanent video recording. UI Automation metadata is preferred where it is
available; screenshots/OCR/VLM remain fallbacks for custom surfaces.

## Delayed triage

The triage worker runs in batches or during idle periods. It may use a small
local model in CPU/RAM, leaving VRAM for the main chat, ASR and TTS models.
Prism-ML and Ternary-Bonsai-8B are candidate profiles only; availability,
Russian quality, RAM use, quantization and throughput must be measured before
they become dependencies.

The worker should return strict structured data:

```text
importance: ignore | retain | promote_candidate
summary: bounded Russian text
topics: bounded labels
confidence: 0..1
source: system_audio | screen | mixed
observed_at / retention_until
provenance: source event IDs and application context
```

`ignore` is dropped. `retain` stays in T1 or is merged into T2. A
`promote_candidate` is still not a fact: it enters a JAWL-controlled promotion
queue and must carry its source, confidence, epistemic type and valid-time
fields. Low-confidence or contradictory observations remain evidence instead
of becoming personality or memory truth.

## Privacy and behavior rules

- Ambient capture is off until explicitly enabled and visibly indicated.
- Deny-listed applications and sensitive window titles produce no ambient
  record; credentials, tokens, calls and private chats are never an intended
  memory source.
- Raw system audio and raw frames are not written to durable storage by the
  companion by default.
- Ambient memory cannot bypass DND, the Turn Arbiter, HostOS policy or approval
  gates. It does not cause proactive speech in the first implementation.
- User microphone turns, explicit screen looks and ambient observations remain
  distinguishable in logs and in the browser controls.
- A user can pause, clear the working buffer, shorten retention and disable
  promotion independently for audio and visual sources.

## Implementation slices

1. Define event envelopes and a fake capture source; test the complete delayed
   path without hardware or model weights.
2. Add the bounded working buffer and deterministic importance/coalescing rules.
3. Benchmark CPU/RAM triage candidates on Russian audio and screen examples.
4. Use the `SystemAudioLoopback` adapter with an optional PyAudioWPatch
   backend, behind an explicit permission and an isolated ASR session.
5. Add idle consolidation into JAWL promotion candidates, with correction and
   forget controls.
6. Run the full compile, unit, HTTP E2E and diff gate after every cross-layer
   runtime change. The expected result is: raw inputs are bounded and dropped,
   observations are attributable, and no ambient event becomes an unapproved
   action.
