# Ambient ASR artifact gate (2026-10-29)

## Finding

The ambient loopback bridge committed every non-empty transcript returned by
final ASR. The microphone endpoint already had a narrow deterministic filter
for obvious noise artifacts, but loopback ASR bypassed it. That allowed single
fillers, repeated-character output, and CJK/Hangul language-switch artifacts
to enter ambient memory and current brain context.

## Change

The predicate now lives in `transcript_quality.py` and is shared by mic and
ambient speech paths. Before commit, ambient transcripts with fewer than two
alphanumeric characters, only one repeated character, or CJK/Hangul characters
are discarded. The bridge counts these as `asr_noise_filtered`; it does not
return filtered text as the last transcript. ASR confidence defaults to 0.0
when the engine supplies none, instead of inventing 0.7 confidence.

YAMNet's music and sound-event worker remains independent and still processes
every current segment, including music-only and JAWL playback cases. This gate
is not a VAD, semantic accuracy test, lyric recognizer, or proof that plausible
Russian/English hallucinations are removed. It only prevents a small set of
known technical artifacts.

## Provenance follow-up

Ambient audio and screen observations are now explicitly stored as
`verified=false`. The loopback ASR fusion entry carries the same marker, so the
brain packet renders the transcript as a model hypothesis. Both delayed-triage
providers receive the verification flag and are instructed to preserve that
uncertainty; generated episodes retain `verified=false` whenever any source
observation is unverified. This labels provenance only; it does not estimate
transcript correctness.

GigaAM supplies no calibrated transcript confidence. Such a transcript keeps
confidence `0.0` and is no longer discarded from the seven-day episode path for
that reason alone when it contains at least eight characters. It can only be
retained under the label `Непроверенная ASR-расшифровка`; deterministic triage does not
promote unscored ASR to a memory candidate. Shorter or obvious artifacts remain
filtered/dropped.

## Verification status

No new regression suite or live run is claimed for this follow-up. Live mixed
loopback and human-reviewed speech references remain open acceptance gates; no
audio was captured or persisted for this change.
