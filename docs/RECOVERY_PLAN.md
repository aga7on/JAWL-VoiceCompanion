# Восстановление и порядок работы

Очередь теперь [TODO D1–D6](../TODO.md); этот файл содержит только инварианты.

- Durable task/intent до действия; при неизвестном эффекте сверка до retry.
- JAWL владеет policy/ledger; Companion не создаёт запасной executor.
- Речь Stop не отменяет goal; turn cancel/task stop/emergency stop различаются.
- Stale generation не возвращается после reconnect/restart.
- Ночной уровень доступа действует в пределах заранее выбранной policy/срока.
- Worker crash восстанавливается ограниченно, без дублирования процессов.
- Reports redacted; cleanup только своих Jobs/paths, upstream read-only.
- Closed panel не равна закрытию brain; audio-device owner требует живого клиента.

Первый конкретный runtime-срез — owned brain entrypoint, см. [STATE](STATE.md).
Не повторять старые завершённые прогоны и не ждать исторические exec IDs.
