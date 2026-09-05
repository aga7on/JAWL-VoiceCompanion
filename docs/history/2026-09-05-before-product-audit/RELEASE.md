> Исторические команды до аудита 2026-09-05. Не запускать: есть пути записи в protected upstream и unsafe launcher. Актуальная инструкция — docs/RELEASE.md в проекте.

# Release, install and rollback

The project is currently a local release candidate. A wheel is useful for
reproducible installation, but it does not include model weights, JAWL,
VoiceMem, TTS/ASR/VLM providers or a Live2D license. Those are external
profiles and must be acceptance-tested on the target machine.

## Build

From `G:\AI\JAWL-VoiceCompanion`:

```powershell
.\scripts\run_full_gate.ps1
.\scripts\build_release.ps1
```

The default Companion ports are control `2367` and presentation/OBS `8766`.
The native JAWL console is a separate service and normally uses `8770`.

The script writes `dist\wheel\*.whl` and a SHA-256 manifest at
`dist\SHA256SUMS.txt`. Do not publish the manifest as a signature: it proves
integrity only after the artifact and manifest have been obtained through a
trusted channel. The build pins `SOURCE_DATE_EPOCH` when the operator has not
provided one, so two builds from the same source tree have identical ZIP
metadata and hash. Signing and provenance storage remain release-owner tasks.

## Clean installation

```powershell
$installRoot = 'G:\AI\JAWL-VoiceCompanion\.release-venv'
py -3.14 -m venv $installRoot
& "$installRoot\Scripts\python.exe" -m pip install --no-deps .\dist\wheel\jawl_voicecompanion-*.whl
& "$installRoot\Scripts\jawl-voicecompanion.exe" --help
```

The wheel carries the control and presentation frontend as data files. Model
providers and optional system-audio support are installed separately. Keep
the JAWL console token in an environment variable; never put it in a command
history, repository file or issue.

The 2026-09-05 release smoke force-reinstalled the freshly built wheel into an
isolated temporary Python 3.14 environment. Import, the installed
`frontend/index.html` and `jawl-voicecompanion --help` all passed. This confirms
the wheel layout and CLI entry point; it is not a target-machine or external-
dependency acceptance test.

## Upgrade and rollback

Use a new virtual environment for a major update, run the full gate, then
switch the launcher/service shortcut to that environment. This makes rollback
an ordinary path change:

```powershell
py -3.14 -m venv G:\AI\JAWL-VoiceCompanion\.release-venv-next
& 'G:\AI\JAWL-VoiceCompanion\.release-venv-next\Scripts\python.exe' -m pip install --no-deps .\dist\wheel\jawl_voicecompanion-*.whl
& 'G:\AI\JAWL-VoiceCompanion\.release-venv-next\Scripts\jawl-voicecompanion.exe' --help
```

Stop the old process before switching ports. Keep the previous environment
until the target-machine live matrix and soak pass; then it can be retired by
the operator. Runtime state under `runtime/` is not silently deleted by an
upgrade. Back it up before changing the JAWL version or its schema.

## Release acceptance

The wheel build is a packaging check, not production evidence. The release
owner must attach the applicable live results from
`docs/TECHNICAL_AUDIT.md`: native JAWL turns/reconnect, HostOS levels 0--3,
real audio/TTS, OBS/avatar rendering, provider startup, restart/lease
recovery and an extended soak. Until then the version remains `release
candidate in validation`.

The latest local artifact is recorded in `dist/SHA256SUMS.txt`; the manifest
is an integrity record, not a signature or proof of live provider support.

## Local restart/soak profile

The dependency-free profile checks repeated Companion startup, health,
resources and vision endpoints, graceful shutdown, and release of both the
control and presentation loopback ports:

```powershell
.\scripts\run_restart_soak.ps1 --cycles 3 --probes 3 `
  --report runtime\restart-soak.json
```

The report is bounded and contains no console token or model payload. A local
three-cycle run passed; target-machine long-duration sidecar/audio/OBS evidence
is still required for release.

## Target-machine release smoke

Attach to an already running target installation; this profile never starts or
stops services. The default run checks both local HTTP surfaces in degraded
mode. Promote external dependencies to requirements explicitly:

```powershell
& 'C:\Python314\python.exe' .\scripts\run_target_release_profile.py `
  --live `
  --url http://127.0.0.1:2367 `
  --presentation-url http://127.0.0.1:8766 `
  --require-jawl-url http://127.0.0.1:8770 `
  --jawl-token $env:CONSOLE_TOKEN `
  --require-dependency asr=http://127.0.0.1:8984 `
  --require-dependency tts=http://127.0.0.1:9889 `
  --require-live2d `
  --report runtime\target-release-profile.json
```

The 2026-09-04 default smoke passed control/presentation boundary checks. The
required mode is intentionally expected to fail until the corresponding live
JAWL, ASR/TTS and licensed Live2D services are actually running.

For a disposable native JAWL startup/policy check, use the guarded wrapper below.
It requires `8773` to be free, starts JAWL with a temporary loopback provider
sink and placeholder key, runs the required target smoke, then tears down the
owned process descendants and temporary env file:

```powershell
.\scripts\run_target_jawl_smoke.ps1
```

The 2026-09-05 run passed JAWL `running=true`, native policy authority `jawl`
at access level `1`, and Companion control/presentation checks. It is not a
provider-quality, ASR/TTS, Live2D, physical OBS or long-duration acceptance test.
Evidence: `runtime\target-release-profile-20260905-jawl.json`.

The browser-render smoke uses an installed Edge/Chrome binary and keeps the
core package free of Playwright:

```powershell
.\scripts\run_browser_render_smoke.ps1
```

It validates rendered control/avatar DOM markers and loopback teardown. It is
not a substitute for real OBS capture, a licensed Live2D bundle, DPI testing,
or a long desktop-pet soak.

## Native Gateway live profile

The source tree contains a dependency-free acceptance harness. It is guarded
against accidental model calls: `--allow-live-turns` is required, and the
default URL must be loopback. The profile performs a reconnect/resume probe, a
real exact-turn cancellation probe, then 100 normal correlated turns. It
validates typed events, final response envelopes, cursor gaps, duplicate
events and sequence continuity. The report does not contain the console
token.

```powershell
$env:JAWL_WEB_URL = 'http://127.0.0.1:8770'
$env:JAWL_CONSOLE_TOKEN = '<token kept outside the repository>'
.\scripts\run_native_gateway_profile.ps1 `
  --allow-live-turns `
  --report artifacts\native-gateway-profile.json
```

Use `--dry-run` to inspect the profile without contacting JAWL. Use
`--skip-cancel` or `--skip-reconnect` only for a diagnostic run; such a report
is not sufficient for release acceptance. A successful mock/unit gate still
does not count as live evidence. On 2026-09-03 the real local JAWL+Ollama
runtime passed the one-turn reconnect/cancel smoke, but its 100-turn soak
stopped at 23/100 after an empty model final answer; the release row remains
open until a stable provider passes the full profile.

Superseding evidence: the isolated local JAWL + Big Pickle profile passed
100/100 correlated turns, reconnect/resume, exact cancellation, final
envelopes, cursor continuity and native HostTerminal tool lifecycle on
2026-09-03. The redacted report is
`runtime/native-gateway-bigpickle-20260903-fixed-100turn.json`. The run used
the loopback-only `scripts/opencode_header_relay.py` because the current
OpenCode Zen route requires the OpenCode CLI User-Agent; this relay is a
temporary test harness, not a production provider gateway or second model.
The result therefore closes this disposable native gateway profile only.

### Native namespace representative profile

The companion repository also includes a read-only namespace profile. It must
point to an already running disposable JAWL console and requires `--live`:

```powershell
& 'C:\Python314\python.exe' .\scripts\run_native_namespace_profile.py `
  --live `
  --url http://127.0.0.1:8773 `
  --token $env:CONSOLE_TOKEN `
  --read-path 'G:\AI\JAWL-Coding\README.md' `
  --directory-path 'G:\AI\JAWL-Coding' `
  --search-path 'G:\AI\JAWL-Coding' `
  --report runtime\native-jawl-namespace-parity.json
```

The 2026-09-04 run observed 93 native catalog entries and passed eight
representative read-only HostOS/HostTerminal/Debug Broker calls. The full
report is `runtime/native-jawl-namespace-parity-20260904.json`. This is route
and catalog evidence only; it does not replace the level 0-3 policy matrix or
the separate mutating/approval/recovery and target-machine gates.

For policy projection across all four native levels, use the guarded matrix:

```powershell
& 'C:\Python314\python.exe' .\scripts\run_native_catalog_matrix.py `
  --live `
  --url http://127.0.0.1:8773 `
  --token $env:CONSOLE_TOKEN `
  --levels 0,1,2,3 `
  --report runtime\native-jawl-catalog-matrix.json
```

The 2026-09-04 disposable run passed availability checks for all 93 catalog
entries and restored the initial policy level. It does not execute mutating
skills or replace the separate action/approval/recovery gates.

The guarded action slice can be run against a disposable JAWL sandbox:

```powershell
& 'C:\Python314\python.exe' .\scripts\run_native_action_profile.py `
  --live `
  --url http://127.0.0.1:8773 `
  --token $env:CONSOLE_TOKEN `
  --sandbox-marker 'G:\path\to\jawl\sandbox\native-action\marker.txt' `
  --sandbox-dir 'G:\path\to\jawl\sandbox' `
  --report runtime\native-jawl-action-parity.json
```

The marker parent must be one new direct child of the supplied sandbox; the
profile refuses overwrites and cleans it through native JAWL. The 2026-09-04
run passed the write/metadata/monitoring/delete slice. It does not claim full
native mutation or approval parity.

### TeraTTSv2 live worker profile

Start the selected local worker, then run the guarded five-request profile:

```powershell
& .\scripts\run_teratts_server.ps1 -Port 9889 -Voice ru_f1
& .\scripts\run_teratts_profile.ps1 `
  --allow-live-model --url http://127.0.0.1:9889 --voice ru_f1 `
  --requests 5 --report runtime\teratts-live-profile.json
```

The 2026-09-04 run passed with complete-response p50 0.429 s, p95 0.487 s
and median RTF 0.149. It measures whole-WAV response time; it is not evidence
of provider-native streaming or real device audio behavior.

### Qwen3-TTS voice-clone worker

The local Qwen3-TTS 12Hz 0.6B Base weights and the Mita reference assets are
external to this repository. Start the worker with the TTS environment that
contains `qwen_tts`:

```powershell
.\scripts\run_qwen3_tts_server.ps1 -Port 9890 -Threads 24
.\scripts\run_web.ps1 --tts-url http://127.0.0.1:9890 --tts-provider qwen
```

The worker fixes the reference audio/text at startup and exposes only the
configured voice label. Its `/health` result explicitly reports
`voice_clone=true` and `emotion_control=false`. A real integrated profile
passed with Qwen ASR, VoiceMem enqueue, JAWL response and a valid 24 kHz WAV;
the TTS request took about 19.3 s on CPU. This is a voice-clone quality path,
not a real-time CPU claim. Keep TeraTTSv2 on port 9889 for live low-latency
fallback.

### Integrated audio pipeline profile

The profile exercises the same route as the browser: bounded PCM16 chunks,
external final ASR, immediate JAWL response, background VoiceMem memory
enqueue and optional TTS:

```powershell
& 'C:\Python314\python.exe' .\scripts\run_audio_pipeline_profile.py `
  --url http://127.0.0.1:2367 `
  --wav 'G:\AI\tts_samples\teratts-v2\welcome.wav' `
  --live --max-end-seconds 8 `
  --report runtime\audio-pipeline-live-profile.json
```

The 2026-09-04 asynchronous run passed with `end_seconds=0.409`, one final
voice response, `memory_sync.status=queued`, and a valid Tera WAV. The Qwen
worker run also passed with `end_seconds=0.391` and a valid 24 kHz WAV. This
does not prove microphone acoustics, true streaming partial ASR,
echo-cancellation or barge-in.

## Native HostOS policy profile

For a disposable JAWL instance, the repository also contains a guarded live
policy matrix. It changes the instance configuration and restarts that
instance at each level, so it must never point at the production JAWL runtime.
The write path must be a newly created disposable file.

```powershell
$env:CONSOLE_TOKEN = '<token kept outside the repository>'
& 'C:\Python314\python.exe' .\scripts\run_native_policy_profile.py --live --url http://127.0.0.1:8773 --token $env:CONSOLE_TOKEN --sandbox-path 'C:\path\to\disposable\sandbox\marker.txt' --outside-read-path 'G:\AI\JAWL-Coding\README.md' --outside-write-path 'G:\AI\JAWL-Coding\runtime\policy-profile-marker.txt' --exercise-write --exercise-emergency-stop --exercise-autonomy --report runtime\native-policy-profile.json
```

The profile refuses non-loopback URLs, waits for a successful native policy
snapshot rather than trusting process status alone, and cleans the write
marker through native recoverable deletion. Its result is one filesystem
policy slice, not full native namespace or target-machine release evidence.

## VoiceMem live profile

The optional VoiceMem profile is guarded by `--allow-live-model` and reports
only bounded timings, event counts and health state. It does not print the
transcript into the JSON report:

```powershell
.\scripts\run_voicemem_profile.ps1 `
  --python 'G:\AI\VoiceMem\.venv\Scripts\python.exe' `
  --wav 'G:\AI\VoiceMem\assets\speech.wav' `
  --local-memory --warmup audio --allow-live-model `
  --report runtime\voicemem-profile.json
```

The bundled fixture is not a Russian acoustic benchmark. Russian acceptance
must use a real Russian recording and the selected Qwen3-ASR/streaming profile.

## Qwen3-ASR final-utterance profile

Start the CPU `llama-server` with `scripts\run_asr_server.ps1`, then run:

```powershell
& .\scripts\run_asr_profile.ps1 `
  --allow-live-model --url http://127.0.0.1:8984/v1 `
  --model Qwen3-ASR-0.6B `
  --wav 'G:\AI\tts_samples\teratts-v2\welcome.wav' `
  --wav 'G:\AI\tts_samples\teratts-v2\poem.wav' `
  --report runtime\asr-live-profile.json
```

The 2026-09-04 run passed with median RTF 0.077 and non-empty Russian
transcripts. This is final-utterance multipart evidence, not streaming
partial-ASR or microphone/echo/barge-in acceptance.
