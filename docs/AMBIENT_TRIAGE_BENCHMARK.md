# Delayed ambient triage benchmark

This benchmark applies only to delayed audio-text triage. Vision/VLM model
selection is intentionally out of scope until the operator finishes the
separate CPU/RAM tests.

## Goal

Choose a small local model/profile that can compress bounded Russian
observations while the main chat keeps its VRAM. The model is not on the
conversational path and must never receive tools or produce `USER_FINAL`.

## Workload

Use a fixed, anonymized corpus of 30-minute-equivalent batches:

- clean game/browser/system speech;
- ordinary low-value commentary;
- errors, warnings, quests, deadlines and explicit “remember” phrases;
- overlapping or contradictory observations;
- private-looking strings that must be suppressed before inference.

Each batch contains 1–64 normalized observations and no raw PCM, screenshots,
credentials or hidden application paths. Keep the same corpus for every model,
quantization and runtime profile.

## Measure

Record for cold and warm runs separately:

- wall time and time to structured result;
- process peak working set and total system RAM delta;
- CPU utilization and whether VRAM usage changes;
- valid JSON rate and provenance accuracy;
- false promotion rate for low-value or private input;
- summary usefulness judged against the source event IDs.

The runner must capture baseline, model-loaded and post-unload snapshots. A
slow model is acceptable for this lane; an unsafe or non-attributable result
is not.

## Acceptance gate

Reject a profile if it uses VRAM, leaks raw input, invents provenance, emits
invalid schema, or turns ambient text into a direct action. Prefer the profile
with the smallest stable RAM footprint that preserves important-event recall;
do not choose by tokens/second alone.

The first implementation exposes a provider contract and an optional Ollama
adapter. The adapter requests structured JSON, temperature 0 and `num_gpu=0`;
`keep_alive=0` unloads after a request by default. A longer keep-alive is an
explicit benchmark setting, not a hidden residency policy.

## Result record

Store benchmark results outside the repository or as a redacted table:

```text
model | quantization | runtime | batch | cold_ms | warm_ms | peak_ram_mb |
vram_delta_mb | cpu_pct | valid_json | provenance | promotion_precision | verdict
```

The selected profile is added only after real measurements. Until then,
deterministic local triage remains the default and the Ollama adapter is
opt-in.
