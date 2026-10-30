# Sensory-history write telemetry (2026-10-29)

## Change

`PerceptionFusion` now records text-free counters for each history-store result
(`recorded`, `coalesced`, `suppressed`, `ignored`, `disabled`, or `error`), plus
the most recent modality and status. Exceptions remain isolated from the live
perception path, but are no longer invisible to the control surface.

The Companion shell status forwards this telemetry to the system-sensor card,
which shows writes, coalesced observations, errors and the latest lane/status.
It now also exposes the store's last successful flush age and distinguishes load,
write, clear, and telemetry errors.
The UI distinguishes store calls from durable flush status. No observation text
or storage path is included in the shell telemetry.

## Limits

The write counters confirm that a history-store call returned a status. Flush
age/error reports the store's own atomic-write result, but does not prove
reopen/recovery or brain retrieval. The focused sensory-history suite passed
8/8, including the archive-preservation regression below; no live profile run
was performed.

## Recovery protection

If an existing history file is oversized, unreadable, or has an unsupported
schema, the store now refuses to overwrite it with an empty/partial snapshot.
The error remains visible until the user explicitly clears the archive. This
preserves the original file for recovery; it does not attempt automatic repair.
The regression covers corrupt JSON, unsupported schema, and the 8 MiB size
limit, then verifies that explicit clear restores writes to a fresh archive.
When a history query is composed while loading is blocked, the brain context
now labels prior history unavailable and marks any returned observations as
current-process-only, preventing a partial archive from looking complete.
If the durable history service is absent or retrieval raises, the brain packet
now says history is unavailable; any short-lived visual fallback is explicitly
marked incomplete and must not be treated as proof that other events did not
occur.
