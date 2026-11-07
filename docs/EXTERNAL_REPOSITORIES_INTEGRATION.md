# Консолидация внешних репозиториев в JAWL-VoiceCompanion V0.5

Документ описывает перевод внешних зависимостей и сторонних репозиториев внутрь дерева `JAWL-VoiceCompanion`.
Цель: устранение жестких привязок к путям `G:\AI\...`, обеспечение автономности, переносимости и сохранение архитектурной философии JAWL (включая ADR-053).

---

## 1. Репозиторий VoiceMem (`G:\AI\VoiceMem` -> `src/voicemem/`, `src/jawl_voicecompanion/voicemem/`)

### Назначение
VoiceMem — система двуполушарной контекстной памяти (Left Brain / Right Brain), классификации слотов запросов, извлечения сущностей и графового связывания фактов.

### Проблема исходной схемы
- Жёсткая зависимость от отдельного виртуального окружения `G:\AI\VoiceMem\.venv`.
- Необходимость внешнего Qdrant-сервера или пакета `mem0` с сетевой телеметрией.
- Риск нарушения политики ADR-053 (попытка записи фактов в долговременную память в обход канонического ядра JAWL).

### Решение и интеграция в JAWL
1. **Вендоринг в дерево**: Код VoiceMem перенесён в `src/voicemem/` и `src/jawl_voicecompanion/voicemem/`.
2. **Политика ADR-053**: Сохранён принцип «долговременную память пишет только JAWL core». VoiceMem предоставляет только спекулятивный контекст (`search`) и передаёт неподтверждённые факты в виде кандидатов (`MEMORY_CANDIDATE`) через эндпоинт `POST /api/ambient-memory/handoff` (`confirm=True`, `trust="unverified_model_observation"`).
3. **Zero-Network SQLite Vector Store**:
   - Реализован класс `LocalSqliteMemory` (в `src/voicemem/leftbrain/mem0_backend_store.py`) с собственным векторным поиском по косинусному сходству, авто-коммитом и закрытием соединений (совместимо с Windows lock semantics).
   - Исключена зависимость от `mem0` и Qdrant.
4. **Встроенный локальный эмбеддер**:
   - `EmbeddingGemmaSensoryCortex` (768d ONNX) обеспечивает локальную генерацию векторных представлений без обращения к HuggingFace или сторонним API.

---

## 2. Репозиторий CrispASR (`G:\AI\crispasr` -> `runtime/bin/crispasr/`)

### Назначение
Высокопроизводительный бинарный движок потокового и файлового распознавания речи (ASR) для Windows x86_64.

### Интеграция в JAWL
1. Исполняемый файл перенесён в `runtime/bin/crispasr/crispasr.exe`.
2. Совмещён с квантованной моделью `runtime/models/asr/gigaam-v3-e2e-rnnt-q8_0.gguf`.
3. Производительность: **15.9x realtime** на CPU (обработка 5 секунд речи за ~314 мс).
4. Все сценарии (`run_integrated_profile.ps1`, `sensory_worker.py`, бенчмарки и зонды) настроены на автоматический поиск бинарника в `runtime/bin/crispasr/crispasr.exe`.

---

## 3. Репозиторий Llama.cpp (`G:\AI\llamacpp-prism`, `G:\AI\llamacpp-taardis` -> `runtime/bin/llama-server/`)

### Назначение
HTTP-сервер инференса LLM/VLM для моделей ядра (SenseNova-Loop 9B, Bonsai-27B, Qwen3.5-0.8B).

### Интеграция в JAWL
1. Консолидирован бинарник `runtime/bin/llama-server/llama-server.exe` (MSVC 19.44, CUDA 13.3).
2. Поддерживает как стандартные архитектуры (Qwen, LLaMA), так и циклические трансформеры (**Looped Transformer**).
3. Проверена работа с моделью `runtime/sensenova-loop/models/SenseNova-Loop-9B-Preview-Q4_K_M-verified.gguf`.
4. В `config/runtime.manifest.json` путь `llama_server_exe` и `brain_server_exe` установлен в `runtime/bin/llama-server/llama-server.exe`.

---

## 4. Репозиторий OmniVoice (`G:\AI\OmniVoice` -> `runtime/models/tts/`, `runtime/omnivoice-venv/`)

### Назначение
Быстрый русскоязычный zero-shot синтез речи (TTS) с клонированием голоса по аудиореференсу.

### Интеграция в JAWL
1. Модель размещена в дереве: `runtime/models/tts/k2-fsa-OmniVoice`.
2. Виртуальное окружение размещено в: `runtime/omnivoice-venv/`.
3. Референсные аудиозаписи перемещены в: `runtime/models/tts/refs/voice_ref_aleksandra.wav` и `ru_ref.wav`.
4. `scripts/omnivoice_server.py` и `scripts/run_integrated_profile.ps1` отдают приоритет in-tree путям и поддерживают аргумент `--model-dir`.

---

## 5. Модели GigaAM v3, Needle3, Laya-Multilingual (`runtime/models/...`)

### Назначение
- `gigaam-v3-e2e-rnnt-q8_0.gguf`: основная модель русской речи (ASR).
- `needle3`: легковесный классификатор намерений и маршрутизатор вызова инструментов (System-1).
- `laya-multilingual`: типизированная классификация состояний и срочности обращений.

### Интеграция в JAWL
Все модели консолидированы в `runtime/models/` и разрешаются относительно корня репозитория через `Path(__file__).resolve().parents[1]` и `Resolve-RepoPath`.

---

## 6. Интерфейс пользователя (`desktop/app.html`, `desktop/app.js`)

### Обновления UX/UI
1. **Индикатор аффекта (`#emotional-resonance`)**: отображает валентность и возбуждение речи аватара в реальном времени.
2. **Индикатор предвыборки памяти (`#prefetch-status`)**: визуализирует статус попадания в кэш локальной памяти.
3. **Карточка амбиентного контекста (`#ambient-prefetch`)**: выводит текущие спекулятивные факты и кандидаты на подтверждение.
4. **Адаптивность**: стилизовано для стандартного окна, компактного HUD и режима OBS-оверлея.
5. **Тестирование**: 100% прохождение 60 нативных Node.js тестов и модульных проверок `desktop/tests/`.
