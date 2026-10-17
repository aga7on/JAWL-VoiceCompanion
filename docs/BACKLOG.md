# Сохранённые требования после первой ежедневной версии

Архивирование не отменяет функции. Полная исходная очередь с исходными
статусами/evidence: [TODO до14Oct](history/2026-10-14-daily-reset/TODO.md).
Старые [x] не означают автоматическую приёмку новой сборки.

| Старые IDs | Что сохраняется | Ближайшая связь |
| --- | --- | --- |
| B0,B1,B2 | Profile/ownership/cancel, речь и просодия | D1/D2/D6; полноценный acoustic full duplex после стабильного Stop |
| B3 | Native JSON/provider compatibility, context, goals/swarm/tools/CDP | D1/D5; весь арсенал сохраняется, UI parity позже |
| P01–P05 | Полная typed библиотека памяти, provenance/correction/erasure, durable T0–T3 и консолидация | D4/D5 минимум, полный lifecycle после daily |
| P06–P10 | Системный звук, vision/action loop, music/affect, defaults | D4; музыкальная модель/пение отдельно |
| U01–U07,U10 | Все настройки JAWL, history/attachments/emoji/slash, memory/tasks UI | D3/D5 минимум; legacy удалять только после parity |
| U08,U09 | LAN/tablet/mobile и actual OBS VRM presentation | Следующая поставка; сохранить существующие поверхности |
| A01–A06 | Референс≥90, лицо/волосы/одежда, физика, VRMA/graph, source/license | Текущие assets остаются, art не блокирует daily |
| S01,S02 | Stream/Restream chat и social accounts | После настройки владельцем, отдельные scoped integrations |
| S03 | AIRI/NEKO/Crane/эмбеддинги/OBS RAM buffer | Research по измеренной необходимости |
| H1–H5 | [Гармоничная архитектура](HARMONIZED_ARCHITECTURE_AND_ROADMAP.md): «Окно-Хамелеон» (Compact HUD ↔ Studio Drawer), двухскоростной контур JAWL, `DuplexCascade` + `OmniVoice`, сенсорная кора `EmbeddingGemma 2` (`eg2`) и 3-слойный игровой агент | D3 (базовый Compact/Studio) + этапы H1–H5 в [TODO](../TODO.md) |
| B4 | Полная упаковка/переносимость/restore/license/resource/release matrix | D6 локальный профиль, универсальная поставка позже |

Музыкальное понимание и напевание не принимаются по ASR transcript или TTS WAV.
Для нового model research сначала малая RU capability/latency проверка, без
скачивания десятков GB до выяснения пригодности. OBS optional adapter, не
обязательная зависимость сенсорного RAM buffer; эмбеддер не заменяет ASR/VLM.

Перенос пункта в активную очередь — явное обновление TODO; не возвращаться
автоматически к старым80–140 человеко-дням как условию первого запуска.
