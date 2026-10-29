# Qwen sensory audio autostart check — 2026-10-28

## Result

**Partial; not a 24/7 acceptance.** Qwen3-Omni received one known music segment through the live Windows loopback and returned `kind=music` in about 1.1 s. The short run verifies startup wiring and one coarse audio classification. It does not establish reliable music style/mood/lyrics analysis, continuous visual-plus-audio quality, or long-run stability.

## Changes

- Added `--ambient-audio-autostart`, guarded so it requires `--ambient-audio`.
- Added explicit launcher option `-StartAmbientAudio` to `run_integrated_profile.ps1` and forwarded it through `run_local_bonsai_integrated.ps1`.
- When requested, composition starts loopback during startup. A failed optional start is logged; doctor still reports missing/stale PCM as not ready.
- Existing behavior stays opt-in: ordinary `--ambient-audio` configures the endpoint but leaves capture stopped. Use `-EnableAmbientAudio -StartAmbientAudio` for an always-on profile. `-NoLocalAudio` keeps local mic/TTS startup off.
- Earlier in this work, audio description moved to its own bounded worker, and the runtime manifest stopped pinning the stale NVIDIA endpoint name so WASAPI default selection follows the active output.

## Live evidence

An isolated Qwen3-Omni profile used the current default endpoint `DigitalOutput (2- NVIDIA High Definition Audio) [Loopback]`. TTS was not started.

- Autostart run: 45 seconds, 23 monitor samples, 0 monitor errors.
- Capture started without a browser/API start request; 1,815 consumer chunks observed.
- Three audio descriptions completed; one segment was classified as `music`, with 1,093 ms last-call latency. Description queue maximum was 0; no Qwen description errors in this run.
- A preceding non-normalized test emitted 4 segments: 3 descriptions were `unknown` and 1 failed. The fixture reached loopback at very low level. After file-level normalization, the autostart run did produce the `music` classification, though loopback remained quiet (peak 474 / RMS 158 in the one-second signal window).
- The lightweight soundscape lane returned `unknown` and zero music windows for these short playback runs. This is not evidence of music-style recognition.
- Launcher report: `status=passed`, `integrated_exit_code=0`, `brain_leaked_after_run=false`.

An additional 80-second run enabled both Qwen vision and Qwen audio against the same Omni endpoint while playing the normalized music fixture:

- Visual: 312 captures, 20 submits and 20 deliveries, 0 stale drops, 0 capture errors; delivery-age p95 641 ms and latest age 1,427 ms.
- Audio: 1,946 consumer chunks and 3 segments; two description results were `unknown`, one request errored, and the bounded description queue stayed empty. The independent soundscape lane reported `music` during part of the run and later returned to `unknown`; no soundscape errors.
- This proves that both lanes stay live on one endpoint for a short interval. It does **not** prove that concurrent audio semantics remain reliable: the audio caption did not recognize the fixture in this combined run, despite the single-lane `music` result above.

## Verification

- `test_ambient_audio.py`: 31 passed.
- `test_doctor.py`: 10 passed.
- `test_launcher_manifest.py`: 19 passed, including headless autostart forwarding with local audio/TTS disabled.
- CLI rejects `--ambient-audio-autostart` without `--ambient-audio`.

## Remaining acceptance work

1. Run the full current visual-plus-audio Qwen profile; the run above did not enable the visual sensor.
2. Repeat with a clear loopback music signal and speech-plus-music clips, and inspect expected-vs-observed labels. Current short tests do not validate lyrics, language, tone, or detailed musical attributes.
3. Run an integrated multi-hour soak on the changed code and require fresh visual/audio evidence, bounded queues, recoverable capture restarts, and stable memory. The earlier 8-hour Qwen soak had visual freshness gaps and a 0.18 GiB free-memory minimum, so it cannot approve this revision.

## JSON response contract follow-up

The 8-hour profile launched at 22:06 Moscow time on 2026-10-28 loaded the pre-fix audio provider and remains useful for visual/runtime endurance only. Its audio caption metrics do not validate the source change below; the running process is not hot-reloaded.

During that run, a direct request to the same Qwen3-Omni endpoint with the provider's prompt-only JSON instruction returned an empty or non-JSON message. A plain natural-language request produced a caption, but it also volunteered a lyric that was not independently verified. A short bounded `json_schema` request against the same normalized music fixture returned a valid object in 0.895 s through `AudioDescriptionService`: `kind=music`, male vocals, fast tempo, distorted guitar, driving drums, energetic mood, and rock/punk tags. The model-reported confidence (0.95) is uncalibrated, and the lyric output was not accepted as ground truth.

`QwenOmniAudioDescriptionProvider` now sends a strict server-side JSON Schema with a concise prompt and 128-token default budget. `tests/test_qwen_omni_audio.py` verifies the request contract. The live direct call passed; integrated capture/fusion with this provider revision and long-run audio acceptance remain open.



### Integrated smoke after provider fix

A fresh isolated profile was restarted at 22:23 Moscow time on 2026-10-28 so the companion loaded the updated provider. The new 8-hour timer and clean telemetry files are active. One 15-second normalized music fixture was played through the current NVIDIA DigitalOutput.

At the first 60-second monitor snapshot: 25 visual deliveries, visual p95 age 593 ms, zero capture errors; 1,741 loopback chunks, zero audio drops; three Qwen audio descriptions, zero description errors, and latest kind `music`. Across captured observations, Qwen emitted two `kind=music` results tagged `rock` (self-reported confidence 0.95, uncalibrated); the independent soundscape lane also processed the clip. The monitor redacted prose and persisted neither source audio nor screen pixels.

This confirms the fixed structured response works through the integrated audio capture/description path. It is one fixture and one early snapshot, not audio diversity or 24/7 acceptance. The restarted profile uses the fixed code; the interrupted pre-fix soak is retained separately as partial runtime evidence only.

### Final soak live music probe

During the isolated final soak (`qwen-audio-default-20261028`), a 10-second portion of the existing 15-second normalized music fixture was played through the system output. The same run continued; no TTS or microphone capture was started.

- Loopback detected nonzero audio during the probe; the capture queue reported zero dropped chunks.
- The integrated Qwen description path emitted a music observation: male vocals, distorted electric guitar, bass and drums, fast rock style, energetic dynamics; tag `rock` (model confidence 0.95, uncalibrated).
- After playback ended, the stream returned to silence and emitted `unknown`, with no description error. The probe did not test lyric transcription.
- At the latest sample the final soak was still running, with no monitor or visual capture errors. This short probe does not complete the eight-hour stability acceptance.

### Known Aqua excerpt during final soak

At 19:44:29 UTC, the live profile processed the existing ten-second `aqua-40-50.wav` fixture through NVIDIA loopback. Qwen classified it as upbeat electronic/dance music with a female vocalist, driving beat, and synth melodies, tagging `dance`, `electronic`, and `female vocalist`. It also returned a lyric fragment that differs from the bench's provisional expected phrase; that annotation is not human-verified, so exact words remain unaccepted. This confirms that the module can attempt lyric quoting, but does not establish lyric accuracy.

At the seven-minute sample, audio-description p95 latency was 859 ms, with zero description errors, queue drops, or loopback drops. The soak process remained alive; visual deliveries were 128 with zero capture errors. The Qwen server's private memory had risen from 24.26 GiB at the first process-tree sample to 28.19 GiB at seven minutes while free system RAM was 43.05 GiB. This early growth must be watched for a plateau over the full run before making a 24/7 claim.

### Memory-cache interpretation checkpoint

The active `llama-server` command was inspected read-only. This build defaults to `--cache-ram 8192` and enables prompt caching; the Qwen brain launcher does not currently override either option. The server's private-memory increase may therefore include prompt-cache warm-up, but the cache's live occupancy is not exposed by this profile, so the cause is not yet confirmed. The current run remains unchanged to preserve the soak; memory and free-RAM trend continue under observation.

At 11.5 minutes, the final soak had 199 visual deliveries, zero visual capture errors/stale drops, 39 audio descriptions, and zero loopback or description errors. The Qwen server had 29.36 GiB private memory with 41.5 GiB system RAM free. The memory rise is still not proven to have plateaued; the launcher leaves the server's bounded 8 GiB prompt cache enabled.

A short Russian text request was also sent directly to the same Qwen server while sensors continued; with the request explicitly encoded as UTF-8 it returned a relevant Russian answer in 228 ms. The subsequent monitor sample showed ongoing visual delivery and no sensor error. This is one low-load contention check, not a voice-turn latency benchmark.
