# LLM Provider Boundary

JAWL owns the canonical conversation and action protocol. Its provider layer
uses OpenAI-compatible JSON Chat Completions messages and may add native
`tool_calls` or JAWL's provider-independent JSON action envelope. QWB-JAWL is
therefore connected behind JAWL's provider configuration, not behind a second
Companion memory or reasoning loop.

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

Before switching regular operation to a provider, validate it through JAWL's
own `OpenAICompatibleProvider`/`QWBProvider` contract suite: ordinary text,
empty content, JSON action envelope, native tool calls, streaming, timeouts,
rate limits, retry classification and restart recovery. The model name alone
does not prove any of those capabilities.

API keys are accepted only through environment variables. They must not be
written to source, docs, audit events, command output or repository history.
