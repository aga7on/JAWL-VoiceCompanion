# Sensory history and ten-minute live acceptance (2026-10-25)

## Implementation

- Added `SensoryHistoryStore`: an in-memory rolling text timeline (up to one hour) and a compact hourly-moment file (seven-day retention).
- The fusion bridge records visual captions, system speech, music, and sound observations with timestamps and source/frame/scene provenance.
- Persistent storage is local JSON under the active profile `data/sensory/weekly-history.json`; raw PCM and screen frames are never stored. Email and common credential-like strings are suppressed.
- History questions can inject the requested time span into the brain prompt; week questions use compact hourly moments. Clearing or disabling ambient memory clears/disables this history.
- Added `/api/sensory-history` status/context access and focused regression tests.

## Verification

- Store, fusion, and web enrichment suite: 25 passed, 4 subtests passed; ambient audio suite: 29 passed.
- `py_compile` passed for the modified runtime modules.
- The live run used the already-running companion, Qwen visual sensor, and NVIDIA DigitalOutput loopback. It did not restart services or save raw media.
- Duration 608.2 s; 199 status samples at roughly three-second intervals; 264 unique text observations (184 visual, 40 system-audio transcript, 40 speech/music status); 0 API/capture errors.
- Screen capture remained fresh (roughly 0.5-0.9 s age in sampled status); audio loopback was running with non-zero RMS. At end: 9,278 visual captures, 1,053 submits, 1,050 deliveries, 0 capture errors; audio bridge 153 transcripts and 572 soundscape windows, last soundscape `unknown` with no tags. No music style was established.

## Model checks and limits

- Current state: the brain described the YouTube browser, a game scene, and the latest Russian dialogue in 2.85 s at run start; at the end it described a YouTube FPS-like scene and dialogue in 3.78 s. These are model descriptions, not verified game labels.
- The VLM repeatedly mislabeled the user's Vice City footage as San Andreas or GTA: Marked Man, and alternated between third-person driving and unrelated-looking first-person scenes. The owner correction (Vice City) is the stronger source for game identity.
- A direct history question without explicit event records returned a generic greeting. When two dated visual observations from the requested earlier interval were supplied explicitly, the brain summarized them in 4.11 s. Supplying four visual/audio records from about two minutes before the end produced a short FPS-like scene and dialogue summary in 2.99 s, but that answer is not independently verified.
- The broad all-session query only summarized selected audio phrases and missed the visual progression. More compact timeline prompts also fell back to a greeting. Therefore full-session synthesis is PARTIAL; the current product brain did not reliably retrieve and summarize all ten minutes unaided.
- This live companion process started before the new persistent store was attached, so the run validates the live sensors and a separate text-only acceptance ledger, not the new store's in-process wiring. Restart/relaunch is required before the profile writes `weekly-history.json` and serves the new `/api/sensory-history` route.

## Artifacts

- Live ledger: `runtime/sensory-history-acceptance-20261025.json` (text observations/counters/model responses only).
- Implementation: `src/jawl_voicecompanion/sensory_history.py`.
- Live harness: `scripts/live_history_acceptance.py`.
