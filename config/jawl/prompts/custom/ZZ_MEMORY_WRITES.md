# Companion memory writes

- Write canonical facts with `SQLStructuredMemory.remember` and ONLY its real
  fields: `kind`, `subject`, `predicate`, `value` (all required). The registered
  optional `memory_key` is valid: use a stable key when a correction is expected.
  Corrections to an existing key use `SQLStructuredMemory.revise_memory`;
  do not create a second active fact or repeat a rejected remember call.
  Other optional arguments must follow the current native signature exactly.
  Example: kind="fact", subject="пользователь", predicate="кодовое слово
  проверки", value="изумруд".
- Search the skill catalog for a signature at most once per cycle. When the
  signature is present, call the tool immediately instead of searching again.
- A single "запомни …" request must finish in 2-3 actions: one write plus one
  short confirmation message.
