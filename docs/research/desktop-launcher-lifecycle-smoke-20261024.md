# Desktop launcher lifecycle smoke — 24 Oct 2026

## Scope

An isolated `goal-tray-smoke-20261024c` profile used the already-running
loopback Qwen endpoint as its temporary brain. JAWL context was 12,288 tokens;
microphone, ambient loopback, ASR, visual capture and TTS were not started.
Electron opened after Companion health became `ready`. The test then wrote a
managed-stop request into this profile's own interface directory using the
exact `runtime_instance_id` returned by health. The stop response carried the
same request ID and instance ID. This exercises launcher acknowledgement and
owned cleanup, but does not exercise a physical tray/button click.

## Findings

- The first Electron attempt failed because this process environment contained
  `ELECTRON_RUN_AS_NODE=1`; Electron executed `main.js` as plain Node and failed
  when `ipcMain` was undefined. `run_integrated_profile.ps1` now clears this
  variable only for the Electron child launch, then restores the parent value.
- After that fix, Electron started and stayed alive until the managed stop.
  `desktop-error.log` was empty. Companion returned `ready` with a unique
  runtime instance ID; managed stop acknowledged the matching request.
- The launcher exited with code 0. All four disposable ports (48765–48768)
  were closed afterwards, the Electron process exited, and no owned profile
  process remained. Existing model endpoints 8990/8995 were left untouched.
- The 250 ms process-tree monitor produced 35 complete snapshots with zero
  enumeration, topology or resource-read errors. During this short cold-start
  window the observed maxima were 17 processes, 2.24 GiB working set, 4.09 GiB
  private bytes and 125% aggregate CPU. These are startup peaks, not steady
  state or 24-hour resource measurements.

## Remaining limits

This is a short lifecycle smoke, not the 30–60 minute current-profile run or
the full-stack 8-hour soak. The stop request was injected into the isolated
profile's managed request file, so the actual UI click path remains unverified.
The Hikari endpoint's 8k context mismatch, real speech answer quality, live
co-watch perception, and long-term resource/worker recovery remain open.

Evidence: `runtime/instances/goal-tray-smoke-20261024c/data/process-tree.jsonl`,
`runtime/instances/goal-tray-smoke-20261024c/logs/integrated/desktop-error.log`,
and the profile's `logs/main.log`.
