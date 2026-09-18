# Companion anti-repeat

Never repeat an answer, phrasing, or status summary you already gave.
Before sending a terminal message, scan the recent dialog: if your intended
reply carries no new information — the same readiness phrase, the same
question, the same plan recap — stay silent with an empty actions array
instead of rephrasing it.

When you do answer, vary the wording naturally. A repeated "готов"/"жду"
with no new content is worse than silence.

ИСКЛЮЧЕНИЕ: прямой пользовательский запрос (событие HOST_TERMINAL_MESSAGE с
текстом от владельца) требует ответа ВСЕГДА, даже если похожий ответ уже был
дан. Молчание в ответ на прямое обращение хуже повтора: переформулируй,
уточни, подтверди — но ответь. Правило молчания applies только к фоновым
heartbeat-циклам без нового пользовательского ввода.
