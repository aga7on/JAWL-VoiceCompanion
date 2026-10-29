# Hikari fusion probe: parallel audio and video evidence

Date: 2026-10-24

## Setup

A single compact text packet was sent to the existing Hikari `local-bonsai2` endpoint on port 8990. It contained separately labeled observations from the Qwen video-only replay, GigaAM CPU ASR, and YAMNet CPU soundscape tags for the same 10-second Russian trailer excerpt. Prompt caching was disabled. No server configuration or other running services were changed.

## Result

The brain returned a complete answer in 3.475 s (323 prompt tokens, 256 completion tokens, 0 cached tokens). It preserved the exact supplied transcript, reproduced the coarse shot list, and declined to invent music genre/source. It also flagged that the dialogue about the dying Sun did not appear aligned with the sparse 1-fps Sun frames, while associating the teacher reply with the classroom shot.

This is a useful proof that independent compact lane summaries can be presented to the brain in one turn. It is not a live parallel-agent or full companion acceptance test: lane outputs were prepared before the brain request, temporal precision is coarse, and only one short excerpt was tested. The model's assertion of A/V timing mismatch needs checking against exact ASR word timestamps and denser visual sampling; do not treat it as ground truth.

## Decision

Keep the modular direction: run audio and video workers independently, emit timestamped evidence with provenance/confidence, then let the brain fuse only overlapping observations. Do not make Qwen Omni or Hikari the sole sensory model based on this probe. The immediate engineering gap is a real-time event packet/fusion contract with timestamps, uncertainty, stale handling, and speaker/scene provenance.

Artifact: `runtime/audio-path-replay/out/hikari-parallel-sensor-fusion-20261024.json`.