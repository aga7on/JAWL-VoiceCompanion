# LLM Provider Boundary

JAWL owns the canonical conversation and action protocol. Its provider layer
uses OpenAI-compatible JSON Chat Completions messages and may add native
`tool_calls` or JAWL's provider-independent JSON action envelope. QWB-JAWL is
therefore connected behind JAWL's provider configuration, not behind a second
Companion memory or reasoning loop.

Service and model-worker boundaries use versioned JSON events because IDs,
provenance, cancellation and tool state must remain machine-checkable. This
does not mean arbitrary model-produced JSON is trusted: every provider result
is parsed against the owning schema, bounded and rejected on ambiguity before
it can become memory, speech or an action.

The Companion's optional `OpenAICompatibleChatClient` is a deliberately small
temporary test adapter. It sends:

```json
{
  "model": "provider-model",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.7,
  "max_tokens": 800
}
```

It reads the standard `choices[0].message.content` field and strips only
visible `<think>`/`<final>` wrappers before the text gateway. It does not
execute tool calls, persist provider sessions, or reproduce JAWL's JSON action
envelope. This keeps temporary TokenRouter/GLM or future local-model tests
replaceable and prevents a second brain from appearing accidentally.

When the provider supports OpenAI SSE, `OpenAICompatibleChatClient.stream()`
requests `stream: true`, emits only reconciled user-visible deltas and keeps
reasoning/tool blocks buffered until their closing marker. The authenticated
Companion `POST /api/chat/stream` endpoint forwards those deltas as NDJSON and
finishes with exactly one `final` event containing the same ResponseEnvelope
used by `POST /api/chat`. Providers without a stream method use a one-delta
compatibility path; JAWL's current correlated web adapter likewise remains
completion-oriented because its upstream event is a completed agent message.
This boundary is text streaming only. The final UI ResponseEnvelope `actions`
are informational and never dispatch tools. Native JAWL tools run through
JAWL's validated provider/tool contract and policy, potentially before the UI final.

Before switching regular operation to a provider, validate it through JAWL's
own `OpenAICompatibleProvider`/`QWBProvider` contract suite: ordinary text,
empty content, JSON action envelope, native tool calls, streaming, timeouts,
rate limits, retry classification and restart recovery. The model name alone
does not prove any of those capabilities.

The production switch procedure is therefore: stop JAWL, configure the new
provider/model in JAWL, choose the verified `json_envelope`, `native` or
capability-driven transport, run JAWL's provider contract suite, then reconnect
Companion through the JAWL Gateway. Do not replace the Companion `--llm-url`
smoke model and assume Heartbeat/tools/memory were preserved.

API keys are accepted only through environment variables. They must not be
written to source, docs, audit events, command output or repository history.

Some hosted gateways apply client-specific routing or rate limits. The
temporary adapter therefore accepts an explicit `--llm-user-agent` value; it
is sent to health, completion and SSE requests without changing the provider
contract. For the current OpenCode CLI installation, the temporary
`big-pickle` smoke uses the CLI-compatible `OpenCode/1.18.11` value. This is a
transport workaround for testing, not a claim that OpenCode is the permanent
JAWL provider.

Raw PCM/frames need not be JSON strings as an architectural rule. Existing
bounded base64 transports remain compatible; any binary optimization must
preserve IDs, consent, cancellation and size limits. The model's JSON action
protocol and the final UI response envelope are distinct schemas: acceptance
must check both, including emotional metadata and error behavior.
