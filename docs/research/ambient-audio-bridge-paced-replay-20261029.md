# Production ambient audio bridge: paced local replay (2026-10-29)

## Scope

Ran the production `AmbientAudioASRBridge` on the existing 10.01-second Aqua
music QA WAV, paced at its 16 kHz mono sample rate. No Companion, TTS, capture
device, or network model service was started. The bridge used the real GigaAM
v3 q8 CrispASR transcriber, EG2 ONNX audio describer, YAMNet ONNX soundscape
detector, `PerceptionFusion`, and an enabled in-memory `AmbientMemoryBuffer`.
YAMNet and EG2 were CPU-only; EG2 used one intra-op thread. The required
VoiceMem interface was a stub and was not called because the final GigaAM lane
was supplied. No transcript, PCM, or memory event was written to disk.

## Result

- Paced replay and drain completed in 11.16 seconds; bridge status `flushed`.
- GigaAM completed one final transcription and one audio observation was
  retained in the temporary memory buffer. Transcript content was not persisted
  or scored against a reference.
- YAMNet processed three soundscape segments, reported `music`, and reached a
  maximum raw Music score of 0.9834. It emitted no stable specific style tag.
- EG2 ran once without error and abstained with kind `unknown`; it did not
  describe the song. Its bounded audio candidate channel was fresh in fusion
  because the independent YAMNet music gate supported it.
- At completion, `speech`, `music`, and `audio_candidates` were fresh in
  `PerceptionFusion`; `audio_description` and `audio_event_candidates` were
  absent for this clip. The fused snapshot was non-empty.
- `raw_audio_persisted=false`, `conversation_turns_emitted=0`, no worker remained
  alive, and no bridge error was reported.

## Assessment

This proves a paced local clip can traverse the real bridge, GigaAM final ASR,
YAMNet, EG2, in-memory retention, and fusion without losing the independent
speech/music/candidate lanes or leaving workers behind. It does not establish
ASR correctness, reliable lyrics, music style/mood, performance under shared
CPU load, physical loopback capture, delivery into a live brain turn, or
continuous live acceptance. EG2's abstention on a known music clip reinforces
that it is not a dependable free-form music describer. YAMNet establishes music
presence here, not genre or soundtrack meaning.

## Brain-bound packet continuation

A second paced replay fed the Russian trailer and Aqua song sequentially through
the same production bridge, then passed the real fusion snapshot through
`make_packet` → `attach_packet` → `split_packet` → `render_packet`. The
round-trip packet was valid and produced non-empty context with `speech`,
`music`, and `audio_candidates`; all three were fresh at packet creation. No
`audio_description` or `audio_event_candidates` were emitted for these samples.
No raw PCM or transcript text was saved, no conversation turn was generated, and
all workers were stopped after flush. This proves real-model channel transport
through serialization, but not a live brain request or semantic accuracy.
