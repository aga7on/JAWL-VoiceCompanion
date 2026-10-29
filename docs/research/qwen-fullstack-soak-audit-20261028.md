# Audit of the Qwen3-Omni eight-hour soak

Source: `runtime/instances/jawl-qwen3-omni-sensors/logs/qwen-fullstack-soak-20261025.jsonl`.
The artifact has a start record, 960 samples at 30-second intervals, and a normal
end record. Elapsed time is 28,800.3 seconds. It does not persist raw screen,
audio, or recognized prose.

## Recomputed results

| Measure | Result |
| --- | ---: |
| Requested / elapsed duration | 8 h / 8 h + 0.3 s |
| Samples | 960 |
| Brain health samples | 947/960 (98.6%) |
| TTS health samples | 937/960 (97.6%) |
| Ambient loopback running samples | 932/960 (97.1%) |
| Samples with no visual-sensor state | 23 (2 separate outage windows) |
| Visual caption fresh samples (missing state counts as not fresh) | 745/960 (77.6%) |
| Samples with measurable caption age | 906/960 |
| Caption age p50 / p95 / maximum (among measurable ages) | 3.31 s / 9.58 s / 39.41 s |
| Longest consecutive non-fresh interval | 47 samples / 23.5 min |
| Final visual counters | 51,559 captures; 3,674 submits; 3,547 deliveries |
| Final cumulative capture errors / stale-result drops | 0 / 0 |
| CPU average / maximum (system samples) | 8.8% / 28.7% |
| Minimum available RAM | 0.18 GiB |
| Minimum free VRAM, GPU 0 / GPU 1 | 641 MiB / 3,222 MiB |

The monitor records `ambient_audio_running`, but not a per-sample successful
Qwen audio-description counter or its last-result age. Therefore the soak proves
loopback service availability for most samples; it does **not** prove that audio
was semantically described continuously. The 23 missing visual states coincide
with 2 windows where brain, TTS, and ambient audio also reported unavailable.
The remaining `companion_status != ready` samples must not be counted as service
outages: the old aggregate doctor stayed degraded because its visual readiness
check was stale. This audit keeps those two signals separate.

## Verdict

**The eight-hour timer completed; integrated unattended acceptance did not pass.**
Visual freshness misses the documented 95% / p95 ≤3 s / no stale gap >5 s gate.
Caption age was absent in 54 samples; those samples count as not fresh in the
freshness percentage, while latency percentiles use only the 906 measured ages.
There are two multi-minute service outages, and one sample reached only 0.18 GiB
available system RAM. Audio-description success and audio-content accuracy are
not recorded in this soak. It also lacks failure-injection/recovery, clean
post-soak restart, and independently labeled mixed-content quality checks.

This is meaningful duration/stability evidence for the experimental
`jawl-qwen3-omni-sensors` profile, not 24/7 readiness. The model and TTS settings
were not changed by this audit.
