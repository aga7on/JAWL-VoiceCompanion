"""Unit tests for MOSS-Live foreground-background duplex coordination."""

import time
import pytest

from jawl_voicecompanion.model_slots import (
    MockModelAdapter,
    ModelCapabilities,
    ModelSlot,
    ModelSlotRegistry,
)
from jawl_voicecompanion.moss_coordinator import (
    BackgroundTask,
    BackgroundTaskManager,
    BackgroundTaskState,
    ForegroundLane,
    MossCoordinationLayer,
    NaturalPauseInjectionItem,
    NaturalPauseInjectionQueue,
    TurnContinuityBuffer,
    TurnInterruptionRecord,
)


def test_natural_pause_injection_queue_priority_and_gating():
    queue = NaturalPauseInjectionQueue(min_silence_sec=0.4)

    # Cannot inject if assistant is speaking
    assert not queue.can_inject(silence_elapsed_sec=0.8, is_assistant_speaking=True)
    # Cannot inject if silence below threshold
    assert not queue.can_inject(silence_elapsed_sec=0.2, is_assistant_speaking=False)
    # Can inject if silence above threshold and assistant silent
    assert queue.can_inject(silence_elapsed_sec=0.5, is_assistant_speaking=False)

    item_low = NaturalPauseInjectionItem(
        item_id="item_low",
        task_id="t1",
        content="Low priority fact",
        priority=20,
    )
    item_high = NaturalPauseInjectionItem(
        item_id="item_high",
        task_id="t2",
        content="High priority alert",
        priority=5,
    )

    queue.push(item_low)
    queue.push(item_high)

    assert len(queue) == 2
    peeked = queue.peek()
    assert peeked is not None
    assert peeked.item_id == "item_high"

    # Drain with insufficient silence returns nothing
    drained = queue.drain_injectable(silence_elapsed_sec=0.2, is_assistant_speaking=False)
    assert len(drained) == 0

    # Drain with sufficient silence pops high priority first
    drained = queue.drain_injectable(silence_elapsed_sec=0.6, is_assistant_speaking=False, max_items=1)
    assert len(drained) == 1
    assert drained[0].item_id == "item_high"
    assert drained[0].status == "injected"
    assert drained[0].injected_at is not None

    assert len(queue) == 1
    popped = queue.pop()
    assert popped is not None
    assert popped.item_id == "item_low"
    assert len(queue) == 0


def test_natural_pause_injection_queue_ttl_expiry():
    queue = NaturalPauseInjectionQueue(min_silence_sec=0.3)
    expired_item = NaturalPauseInjectionItem(
        item_id="exp_1",
        task_id="t_old",
        content="Stale news",
        priority=10,
        ready_at=time.time() - 100.0,
        ttl_sec=5.0,
    )
    queue.push(expired_item)
    assert queue.peek() is None

    # Drain skips expired item and marks it expired
    drained = queue.drain_injectable(silence_elapsed_sec=1.0, is_assistant_speaking=False)
    assert len(drained) == 0
    assert expired_item.status == "expired"


def test_turn_continuity_buffer():
    buf = TurnContinuityBuffer(max_records=3, ttl_sec=10.0)
    assert not buf.has_interruption()
    assert buf.peek_resumption() is None
    assert buf.format_resumption_context() == ""

    rec = buf.push_interruption(
        turn_id="turn_1",
        original_prompt="Расскажи про квазары",
        spoken_text="Квазары это яркие",
        unspoken_text="активные ядра галактик с черными дырами",
        user_barge_in_text="А сколько им лет?",
    )

    assert buf.has_interruption()
    peek = buf.peek_resumption()
    assert peek is not None
    assert peek.turn_id == "turn_1"
    assert not peek.resumed

    ctx = buf.format_resumption_context()
    assert "Квазары это яркие" in ctx
    assert "активные ядра галактик с черными дырами" in ctx

    popped = buf.pop_resumption()
    assert popped is not None
    assert popped.turn_id == "turn_1"
    assert popped.resumed is True
    # Once popped/resumed, has_interruption is False
    assert not buf.has_interruption()


def test_foreground_lane_streaming_and_cancellation():
    registry = ModelSlotRegistry()
    mock_adapter = MockModelAdapter(
        name="fg_mock",
        canned_responses=["Привет мир, как твои дела?"],
    )
    registry.register(ModelSlot.FOREGROUND_BRAIN, mock_adapter)

    lane = ForegroundLane(registry)
    assert not lane.is_streaming

    tokens = list(
        lane.stream_turn(
            turn_id="turn_test_1",
            messages=[{"role": "user", "content": "Привет"}],
        )
    )
    assert "".join(tokens) == "Привет мир, как твои дела?"
    assert not lane.is_streaming


def test_foreground_lane_cancel_current():
    registry = ModelSlotRegistry()
    mock_adapter = MockModelAdapter(
        name="fg_mock",
        canned_responses=["Первое предложение. Второе предложение. Третье предложение."],
    )
    registry.register(ModelSlot.FOREGROUND_BRAIN, mock_adapter)

    lane = ForegroundLane(registry)
    gen = lane.stream_turn(
        turn_id="turn_cancel",
        messages=[{"role": "user", "content": "Привет"}],
    )

    token1 = next(gen)
    assert lane.is_streaming
    spoken, unspoken = lane.cancel_current()
    assert not lane.is_streaming
    assert len(spoken) > 0


def test_background_task_manager_execution_and_auto_injection():
    registry = ModelSlotRegistry()
    mock_adapter = MockModelAdapter(
        name="bg_mock",
        canned_responses=["Глубокий анализ завершен: всё в норме."],
    )
    registry.register(ModelSlot.BACKGROUND_REASONER, mock_adapter)

    pause_queue = NaturalPauseInjectionQueue(min_silence_sec=0.1)
    bg_mgr = BackgroundTaskManager(registry, pause_queue, max_workers=2)

    # Task with custom runner
    def custom_runner(task: BackgroundTask) -> dict:
        return {"speech_summary": "Погода ясная, +22 градуса."}

    task1 = bg_mgr.submit_task(
        task_type="weather_lookup",
        payload={"city": "Moscow"},
        priority=5,
        runner_fn=custom_runner,
        auto_inject=True,
    )

    # Wait for completion
    for _ in range(50):
        if task1.status == BackgroundTaskState.COMPLETED:
            break
        time.sleep(0.02)

    assert task1.status == BackgroundTaskState.COMPLETED
    assert task1.result == {"speech_summary": "Погода ясная, +22 градуса."}
    assert len(pause_queue) == 1

    inj = pause_queue.pop()
    assert inj is not None
    assert inj.content == "Погода ясная, +22 градуса."

    # Task using default reasoner against BACKGROUND_REASONER slot
    task2 = bg_mgr.submit_task(
        task_type="reasoning",
        payload={"prompt": "Вычисли вероятность"},
        priority=10,
        auto_inject=True,
    )

    for _ in range(50):
        if task2.status == BackgroundTaskState.COMPLETED:
            break
        time.sleep(0.02)

    assert task2.status == BackgroundTaskState.COMPLETED
    assert "Глубокий анализ" in str(task2.result)

    bg_mgr.shutdown(wait=True)


def test_background_task_cancellation():
    registry = ModelSlotRegistry()
    pause_queue = NaturalPauseInjectionQueue()
    bg_mgr = BackgroundTaskManager(registry, pause_queue, max_workers=2)

    def slow_runner(task: BackgroundTask):
        for _ in range(20):
            if task.cancel_event.is_set():
                return None
            time.sleep(0.05)
        return "done"

    task = bg_mgr.submit_task(
        task_type="slow_calc",
        payload={},
        runner_fn=slow_runner,
    )

    time.sleep(0.03)
    cancelled = bg_mgr.cancel_task(task.task_id)
    assert cancelled is True

    time.sleep(0.1)
    assert task.status == BackgroundTaskState.CANCELLED

    bg_mgr.shutdown(wait=True)


def test_moss_coordination_layer_duplex_barge_in_and_resumption():
    registry = ModelSlotRegistry()
    mock_fg = MockModelAdapter(
        name="fg_mock",
        canned_responses=["Сегодня прекрасный солнечный день для прогулок по парку."],
    )
    mock_bg = MockModelAdapter(
        name="bg_mock",
        canned_responses=["Фоновый расчет готов."],
    )
    registry.register(ModelSlot.FOREGROUND_BRAIN, mock_fg)
    registry.register(ModelSlot.BACKGROUND_REASONER, mock_bg)

    coordinator = MossCoordinationLayer(
        registry=registry,
        min_silence_sec=0.3,
    )

    # 1. Backchannel test: user says "угу" while assistant is speaking
    is_cut, record = coordinator.handle_barge_in(
        user_utterance="угу",
        spoken_prefix="Сегодня прекрасный",
        full_text="Сегодня прекрасный солнечный день для прогулок по парку.",
    )
    assert is_cut is False
    assert record is None
    assert not coordinator.continuity_buffer.has_interruption()

    # 2. Substantive interruption: user says "стой, подожди"
    epoch_before = coordinator.generation_epoch
    is_cut, record = coordinator.handle_barge_in(
        user_utterance="стой, подожди",
        spoken_prefix="Сегодня прекрасный",
        full_text="Сегодня прекрасный солнечный день для прогулок по парку.",
    )
    assert is_cut is True
    assert record is not None
    assert coordinator.generation_epoch > epoch_before
    assert record.unspoken_text == "солнечный день для прогулок по парку."
    assert coordinator.continuity_buffer.has_interruption()

    # 3. Next turn: handle_user_turn automatically enriches prompt with resumption context
    gen = coordinator.handle_user_turn(
        user_utterance="А что там с дождем?",
        auto_resume_continuity=True,
    )
    tokens = list(gen)
    assert len(tokens) > 0

    # Interruption record was popped and marked resumed
    assert not coordinator.continuity_buffer.has_interruption()

    # 4. Background task dispatch and natural pause injection
    task = coordinator.dispatch_background_task(
        task_type="deep_calc",
        payload={"prompt": "Рассчитай траекторию"},
        auto_inject=True,
    )

    for _ in range(50):
        if task.status == BackgroundTaskState.COMPLETED:
            break
        time.sleep(0.02)

    assert task.status == BackgroundTaskState.COMPLETED

    # Check pause injection during silence
    injected = coordinator.on_vad_silence(
        silence_elapsed_sec=0.5,
        assistant_speaking=False,
    )
    assert len(injected) == 1
    assert "Фоновый расчет готов." in injected[0].content

    # Snapshot inspection
    snapshot = coordinator.get_state_snapshot()
    assert "generation_epoch" in snapshot
    assert "pause_queue_depth" in snapshot
    assert "continuity_records" in snapshot
    assert len(snapshot["background_tasks"]) >= 1

    coordinator.shutdown()
