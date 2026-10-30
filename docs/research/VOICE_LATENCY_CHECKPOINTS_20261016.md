# Голосовая задержка и native prompt cache — 16Oct2026

Это разбор завершённой real-model WAV серии, не новый runtime или принятый
latency target. Код текущего восьмичасового soak остаётся неизменным.

## Измерено

[Voice20 receipt](../../runtime/owned-voice-series-20261016-r2.json) подтверждает
20 полных ходов /app с GigaAM, Hikari Bonsai-2 GPU1 и OmniVoice. Три WAV
повторялись; physical speech-end/audibility не измерялись.
[Общая задержка](../../runtime/owned-voice-latency-20261016.json):
dispatch voice/end→first WebAudio p50=8.338с,p95=11.964с,min=6.377с,max=13.286с.

[Стадии20 ходов](../../runtime/owned-voice-stages-20261016.json) сопоставлены
по точному turn_id: native action journal даёт ReAct trace/start и первый
успешный terminal action, SQL ticks — только публичные numeric LLM metrics.
Текст контекста/thoughts/answers не экспортирован.

| Стадия | p50, с | p95, с | Что охватывает |
| --- | ---: | ---: | --- |
| Native цикл до первой terminal delivery |6.438|9.879|context, LLM, native actions |
| Сумма LLM calls одного хода |6.226|9.172|provider wall time; prefill/decode не разделены |
| Остальное внутри native цикла |0.189|0.453|context/actions/native overhead |
| HTTP время вне native цикла |0.384|0.436|ASR/reset/admission/projection; не isolated ASR |
| Ответ HTTP→first WebAudio |1.088|2.233|client/TTS/chunk/decode/audio start |

Квантили отдельных стадий не складываются в квантиль общей задержки.
20 ходов дали22 LLM calls:18 одиночных, два по два. В одном ходе модель
запланировала10 terminal actions; guard подавил повторы, фактический
assistant.final остался один. Поэтому ненужные циклы не объясняют основной
разрыв до1–3с. GigaAM batch spawn существует, но measured HTTP residual
около0.38с не подтверждает гипотезу о нескольких секундах ASR startup.

Для22 calls: prompt tokens12574–18718, median14641; completion tokens107–578,
median155. Provider cached tokens ровно8017 во всех22 calls. Это указывает
на возможный повторный prefill значительной dynamic части; отдельные
prompt/decode/GPU-contention timings в сохранённых native metrics отсутствуют.
Причина высокого LLM wall time ещё не доказана одним cache counter.

## Проверено в установленном сервере

[Capability receipt](../../runtime/llama-checkpoint-capabilities-20261016.json)
фиксирует SHA actual llama-server binary и его help. Выбранный GGUF header
даёт general.architecture=qwen35; исходник qwen35.cpp использует recurrent/SSM.
У этого сервера есть --ctx-checkpoints и --checkpoint-min-step; default
spacing8192 tokens. Default checkpoint count32 подтверждён help/source.

В G:/AI/llamacpp-prism/tools/server/server-context.cpp create_checkpoint
сохраняет partial recurrent state, а восстановление выбирает допустимый
checkpoint до common-prefix boundary. Prefill создаёт checkpoint у начала
последнего user message и после minimum spacing. В common/common.h
checkpoint_min_step=8192, n_ctx_checkpoints=32.

Следующий обоснованный performance experiment после текущего soak —
сравнить spacing8192 с1024 на одинаковых native turns/полном context budget.
Это пока гипотеза, не включённая оптимизация. Нужны actual server prompt_n/
prompt_ms/predicted_n/predicted_ms, cached tokens, response completion/error,
постусловия действий и exact owned RSS/VRAM. Более частые checkpoints
добавляют state copies/RAM и могут вытеснить полезный ранний checkpoint;
ускорение нельзя считать доказанным по наличию CLI flag.

Не менять модель/GPU/context window, не урезать native discovery/memory,
не переставлять native attention-priority sections ради предполагаемого cache
и не считать read-only server capability check измерением выигрыша.


## Изолированная подготовка эксперимента

[Candidate receipt](../../runtime/d2-cache-candidate-20261016.json) и
[reviewable patch](../../runtime/d2-cache-candidate-20261016.patch) относятся
к отдельному worktree runtime/experiments/d2-cache-worktree-20261016.
Owned brain holder принимает explicit --checkpoint-min-step/--ctx-checkpoints,
не меняет server defaults при отсутствии flags и отвергает invalid bounds
до spawn.13 focused tests/4 subtests и worktree CodeSee validator PASS.
Model/GPU/context/transport сохраняются. В основной runtime изменение
не перенесено; real-model latency/RSS benchmark не выполнялся.


### A/B/B/A измеритель подготовлен

[Preparation receipt](../../runtime/d2-cache-benchmark-preparation-20261016.json)
и [candidate patch](../../runtime/d2-cache-benchmark-candidate-20261016.patch)
описывают opt-in native server timing hook, warm20 trial и A/B/B/A runner.
Сохраняются только cache_n/prompt_n/prompt_ms/predicted_n/predicted_ms.
Warmup исключён; exact turn→trace→request matching учитывает все calls,
missing timings/duplicate scope/changed model or prompt bank/cleanup FAIL
не допускают сравнения. RSS измеряется только в exact owned Jobs.

30 focused tests/54 subtests и CodeSee validator PASS. Bootstrap на actual
native classes подтвердил hook и cleanup без запуска модели. Native SDK
сохраняет server timing extras. Старый snapshot из worktree checkout имел
hash mismatch и сохранён; для эксперимента подготовлена отдельная verified
348-file копия с тем же SHA, что у main runtime, в
runtime/jawl-sources/jawl-20261016-cache-baseline. Это не изменение upstream.

После текущего soak команда из отдельного worktree:

```powershell
python -X utf8 -B scripts/run_cache_benchmark.py --live --baseline-step 8192 --candidate-step 1024 --checkpoints 32 --report runtime/cache-abba-unique.json
```

Все четыре real-model trials ещё не запускались. Promotion не выполняется
автоматически; сравнение native text не заменяет повтор voice/actions и
проверку расхода памяти. Model/GPU/window/discovery остаются прежними.
