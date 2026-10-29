# Gemini 3.8 Flash local endpoint candidate — 2026-10-29

- Display name: Gemini 3.8 Flash
- OpenAI-compatible model ID: `gemini-3.8-flash`
- Base URL: `http://127.0.0.1:8045/v1`
- Authentication variable expected by the managed JAWL launcher: `LLM_API_KEY_1`
- Status: recorded as a candidate only; it has not been selected as the active brain or run through JAWL.
- Verification: local endpoint on port 8045 responded to `GET /v1/models` without sending a credential and listed `gemini-3.8-flash` among 14 IDs.
- The credential supplied in chat was not copied to this file or a tracked configuration. It must be provided through a protected environment/secret store when this candidate is run.

The `hikari-clean-20261029` profile was stopped cleanly before recording this candidate. Its managed ports are down and its run lock is free. The endpoint on port 8045 remains listening.
