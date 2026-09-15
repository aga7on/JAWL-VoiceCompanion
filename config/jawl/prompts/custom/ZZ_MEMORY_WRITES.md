# Companion memory writes

- Write canonical facts with `SQLStructuredMemory.remember` and ONLY its real
  fields: `kind`, `subject`, `predicate`, `value` (all required). Never invent
  or rename fields such as `memory_key`.
  Example: kind="fact", subject="пользователь", predicate="кодовое слово
  проверки", value="изумруд".
- Search the skill catalog for a signature at most once per cycle. When the
  signature is present, call the tool immediately instead of searching again.
- A single "запомни …" request must finish in 2-3 actions: one write plus one
  short confirmation message.
