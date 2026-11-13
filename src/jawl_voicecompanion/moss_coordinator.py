"""MOSS-Live Foreground-Background Duplex Coordination Layer for JAWL VoiceCompanion.

Implements the MOSS-Live duplex paradigm:
1. Foreground Lane: Real-time streaming dialogue, cooperative cancellation on barge-in,
   and backchannel tolerance.
2. Background Lane (BackgroundTaskManager): Asynchronous tool tasks, ReAct reasoning,
   retrieval, and deep cognitive calculations.
3. Natural Pause Injection Queue: Buffers background task completions and injects
   them during natural speech pauses or turn boundaries without rudely interrupting
   active speech.
4. Turn Continuity Buffer: Stores interrupted utterances mid-speech to allow
   smooth resumption after a user barge-in is resolved.
5. MossCoordinationLayer: Unified orchestrator binding ModelSlotRegistry, lanes,
   pause injection, and turn continuity.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
import enum
import logging
import threading
import time
from typing import Any, Callable, Iterator
import uuid

from .duplex_cascade import DuplexCascadeArbiter, is_user_backchannel
from .model_slots import (
    ModelAdapter,
    ModelSlot,
    ModelSlotRegistry,
)

logger = logging.getLogger("jawl.moss_coordinator")


class BackgroundTaskState(str, enum.Enum):
    """Lifecycle states for background tasks."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """Asynchronous background cognitive or tool task."""

    task_id: str
    task_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 10
    status: BackgroundTaskState = BackgroundTaskState.PENDING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def duration_sec(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "priority": self.priority,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": round(self.duration_sec, 3),
            "cancelled": self.cancel_event.is_set(),
        }


@dataclass
class NaturalPauseInjectionItem:
    """Buffered message or action to inject during conversational silence."""

    item_id: str
    task_id: str
    content: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    priority: int = 10
    category: str = "background_result"
    ready_at: float = field(default_factory=time.time)
    injected_at: float | None = None
    status: str = "pending"
    ttl_sec: float = 60.0

    @property
    def is_expired(self) -> bool:
        if self.status != "pending":
            return False
        return (time.time() - self.ready_at) > self.ttl_sec

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "task_id": self.task_id,
            "content": self.content,
            "structured_data": self.structured_data,
            "priority": self.priority,
            "category": self.category,
            "ready_at": self.ready_at,
            "injected_at": self.injected_at,
            "status": self.status,
            "is_expired": self.is_expired,
        }


class NaturalPauseInjectionQueue:
    """Thread-safe priority queue for natural speech pause injection.

    Enforces MOSS-Live principle: background task results MUST NOT rudely
    cut off user speech or active assistant speech. They are held until
    sufficient silence is detected.
    """

    def __init__(self, min_silence_sec: float = 0.45) -> None:
        self.min_silence_sec = float(min_silence_sec)
        self._lock = threading.Lock()
        self._items: list[NaturalPauseInjectionItem] = []

    def push(self, item: NaturalPauseInjectionItem) -> None:
        """Add an item sorted by priority (lowest number = highest priority) and timestamp."""
        with self._lock:
            self._items.append(item)
            self._items.sort(key=lambda x: (x.priority, x.ready_at))

    def peek(self) -> NaturalPauseInjectionItem | None:
        """Inspect the highest-priority pending item without popping."""
        with self._lock:
            for it in self._items:
                if it.status == "pending" and not it.is_expired:
                    return it
            return None

    def pop(self) -> NaturalPauseInjectionItem | None:
        """Pop the highest-priority pending, non-expired item."""
        with self._lock:
            for i, it in enumerate(self._items):
                if it.status == "pending":
                    if it.is_expired:
                        it.status = "expired"
                        continue
                    item = self._items.pop(i)
                    item.status = "injected"
                    item.injected_at = time.time()
                    return item
            return None

    def can_inject(
        self,
        silence_elapsed_sec: float,
        is_assistant_speaking: bool = False,
        min_silence_override: float | None = None,
    ) -> bool:
        """Check if conditions permit injecting background results."""
        if is_assistant_speaking:
            return False
        threshold = self.min_silence_sec if min_silence_override is None else float(min_silence_override)
        return float(silence_elapsed_sec) >= threshold

    def drain_injectable(
        self,
        silence_elapsed_sec: float,
        is_assistant_speaking: bool = False,
        max_items: int = 1,
        min_silence_override: float | None = None,
    ) -> list[NaturalPauseInjectionItem]:
        """Drain items eligible for injection if conversational silence permits."""
        if not self.can_inject(silence_elapsed_sec, is_assistant_speaking, min_silence_override):
            return []

        injected: list[NaturalPauseInjectionItem] = []
        with self._lock:
            i = 0
            while i < len(self._items) and len(injected) < max_items:
                it = self._items[i]
                if it.status != "pending":
                    i += 1
                    continue
                if it.is_expired:
                    it.status = "expired"
                    i += 1
                    continue
                item = self._items.pop(i)
                item.status = "injected"
                item.injected_at = time.time()
                injected.append(item)
        return injected

    def prune_expired(self) -> int:
        """Remove expired items from queue."""
        with self._lock:
            initial = len(self._items)
            now = time.time()
            self._items = [
                it for it in self._items
                if it.status == "pending" and (now - it.ready_at) <= it.ttl_sec
            ]
            return initial - len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [it.to_dict() for it in self._items]

    @property
    def items(self) -> list[NaturalPauseInjectionItem]:
        with self._lock:
            return list(self._items)

    def __len__(self) -> int:
        with self._lock:
            return sum(1 for it in self._items if it.status == "pending" and not it.is_expired)

    def qsize(self) -> int:
        """Return number of pending unexpired injection items."""
        return len(self)


@dataclass
class TurnInterruptionRecord:
    """Record of an assistant turn interrupted by user barge-in."""

    turn_id: str
    original_prompt: str
    spoken_text: str
    unspoken_text: str
    interrupted_at: float = field(default_factory=time.time)
    user_barge_in_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    resumed: bool = False
    resumed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "original_prompt": self.original_prompt,
            "spoken_text": self.spoken_text,
            "unspoken_text": self.unspoken_text,
            "interrupted_at": self.interrupted_at,
            "user_barge_in_text": self.user_barge_in_text,
            "metadata": self.metadata,
            "resumed": self.resumed,
            "resumed_at": self.resumed_at,
        }


class TurnContinuityBuffer:
    """Stores interrupted turns so the assistant can seamlessly resume thoughts."""

    def __init__(self, max_records: int = 5, ttl_sec: float = 120.0) -> None:
        self.max_records = max(1, int(max_records))
        self.ttl_sec = float(ttl_sec)
        self._lock = threading.Lock()
        self._records: list[TurnInterruptionRecord] = []

    def push_interruption(
        self,
        turn_id: str,
        original_prompt: str,
        spoken_text: str,
        unspoken_text: str,
        user_barge_in_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TurnInterruptionRecord:
        """Register an interrupted turn."""
        record = TurnInterruptionRecord(
            turn_id=turn_id,
            original_prompt=original_prompt,
            spoken_text=spoken_text.strip(),
            unspoken_text=unspoken_text.strip(),
            interrupted_at=time.time(),
            user_barge_in_text=user_barge_in_text.strip(),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._records.append(record)
            if len(self._records) > self.max_records:
                self._records.pop(0)
        return record

    def has_interruption(self) -> bool:
        """True if there is an unresumed, unexpired interruption record."""
        return self.peek_resumption() is not None

    def peek_resumption(self) -> TurnInterruptionRecord | None:
        """Inspect the most recent unresumed, unexpired interruption."""
        with self._lock:
            now = time.time()
            for rec in reversed(self._records):
                if not rec.resumed and (now - rec.interrupted_at) <= self.ttl_sec:
                    if rec.unspoken_text:
                        return rec
            return None

    def pop_resumption(self) -> TurnInterruptionRecord | None:
        """Fetch and mark the most recent unresumed interruption as resumed."""
        with self._lock:
            now = time.time()
            for rec in reversed(self._records):
                if not rec.resumed and (now - rec.interrupted_at) <= self.ttl_sec:
                    if rec.unspoken_text:
                        rec.resumed = True
                        rec.resumed_at = now
                        return rec
            return None

    def format_resumption_context(self) -> str:
        """Generate continuity prompt inject for the next conversational turn."""
        rec = self.peek_resumption()
        if not rec or not rec.unspoken_text:
            return ""
        spoken = f'"{rec.spoken_text}"' if rec.spoken_text else "начало ответа"
        return (
            f"[Контекст прерванной реплики: в предыдущем ответе ты успел сказать {spoken}, "
            f'но пользователь перебил тебя. Недосказанная мысль была: "{rec.unspoken_text}". '
            f"Ответь на новый вопрос пользователя, и при естественной возможности кратко свяжи или заверши недосказанное.]"
        )

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [rec.to_dict() for rec in self._records]


class ForegroundLane:
    """Foreground conversational lane executing real-time streaming dialogue."""

    def __init__(self, registry: ModelSlotRegistry) -> None:
        self.registry = registry
        self._lock = threading.Lock()
        self._current_turn_id: str | None = None
        self._is_streaming: bool = False
        self._active_cancel_event: threading.Event | None = None
        self._spoken_accumulator: list[str] = []
        self._full_generation: list[str] = []

    @property
    def is_streaming(self) -> bool:
        with self._lock:
            return self._is_streaming

    @property
    def current_turn_id(self) -> str | None:
        with self._lock:
            return self._current_turn_id

    def stream_turn(
        self,
        turn_id: str,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        on_token: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream generation from the FOREGROUND_BRAIN slot with cooperative cancellation."""
        with self._lock:
            self._current_turn_id = turn_id
            self._is_streaming = True
            self._active_cancel_event = cancel_event or threading.Event()
            self._spoken_accumulator.clear()
            self._full_generation.clear()

        adapter = self.registry.get_with_fallback(ModelSlot.FOREGROUND_BRAIN)
        if adapter is None:
            with self._lock:
                self._is_streaming = False
            raise RuntimeError("No model adapter available for FOREGROUND_BRAIN slot")

        token_generator = adapter.stream_generate(
            messages=messages,
            system_prompt=system_prompt,
            cancel_event=self._active_cancel_event,
            **kwargs,
        )

        try:
            for token in token_generator:
                if self._active_cancel_event and self._active_cancel_event.is_set():
                    break
                with self._lock:
                    self._full_generation.append(token)
                    self._spoken_accumulator.append(token)
                if on_token is not None:
                    on_token(token)
                yield token
        finally:
            with self._lock:
                self._is_streaming = False

    def mark_spoken(self, text_chunk: str) -> None:
        """Record chunks that have actually been played back by TTS."""
        with self._lock:
            self._spoken_accumulator.append(text_chunk)

    def cancel_current(self) -> tuple[str, str]:
        """Cancel active generation and return (spoken_text, unspoken_remaining)."""
        with self._lock:
            if self._active_cancel_event:
                self._active_cancel_event.set()
            self._is_streaming = False
            spoken = "".join(self._spoken_accumulator)
            full = "".join(self._full_generation)
            unspoken = full[len(spoken):] if len(full) > len(spoken) else ""
            return spoken, unspoken


class BackgroundTaskManager:
    """Asynchronous background cognitive runner for tool calls, reasoning, and retrieval."""

    def __init__(
        self,
        registry: ModelSlotRegistry,
        pause_queue: NaturalPauseInjectionQueue,
        max_workers: int = 4,
    ) -> None:
        self.registry = registry
        self.pause_queue = pause_queue
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="moss_bg_",
        )
        self._lock = threading.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._futures: dict[str, concurrent.futures.Future[Any]] = {}

    def submit_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: int = 10,
        runner_fn: Callable[[BackgroundTask], Any] | None = None,
        auto_inject: bool = True,
    ) -> BackgroundTask:
        """Submit a background task for asynchronous execution."""
        task_id = f"bg_{uuid.uuid4().hex[:8]}"
        task = BackgroundTask(
            task_id=task_id,
            task_type=task_type,
            payload=dict(payload),
            priority=int(priority),
            status=BackgroundTaskState.PENDING,
        )

        with self._lock:
            self._tasks[task_id] = task

        def _execute() -> None:
            task.started_at = time.time()
            task.status = BackgroundTaskState.RUNNING
            try:
                if task.cancel_event.is_set():
                    task.status = BackgroundTaskState.CANCELLED
                    return

                if runner_fn is not None:
                    res = runner_fn(task)
                else:
                    res = self._default_background_runner(task)

                if task.cancel_event.is_set():
                    task.status = BackgroundTaskState.CANCELLED
                    return

                task.result = res
                task.status = BackgroundTaskState.COMPLETED
                task.finished_at = time.time()

                if auto_inject:
                    content_str = self._format_result_content(res)
                    if content_str:
                        inj_item = NaturalPauseInjectionItem(
                            item_id=f"inj_{uuid.uuid4().hex[:8]}",
                            task_id=task.task_id,
                            content=content_str,
                            structured_data={"task_type": task.task_type, "result": res},
                            priority=task.priority,
                            category="background_result",
                        )
                        self.pause_queue.push(inj_item)
            except Exception as exc:
                task.error = str(exc)
                task.status = BackgroundTaskState.FAILED
                task.finished_at = time.time()
                logger.warning("Background task %s failed: %s", task.task_id, exc)

        fut = self.executor.submit(_execute)
        with self._lock:
            self._futures[task_id] = fut

        return task

    def _default_background_runner(self, task: BackgroundTask) -> Any:
        """Default reasoning execution against BACKGROUND_REASONER slot."""
        adapter = self.registry.get_with_fallback(ModelSlot.BACKGROUND_REASONER)
        if adapter is None:
            raise RuntimeError("No model adapter available for BACKGROUND_REASONER")

        prompt = task.payload.get("prompt") or task.payload.get("query") or ""
        system = task.payload.get("system_prompt") or "You are a deep analytical background reasoner."
        tools = task.payload.get("tools")

        if tools:
            return adapter.generate_with_tools(
                messages=[{"role": "user", "content": str(prompt)}],
                tools=tools,
                system_prompt=system,
                cancel_event=task.cancel_event,
            )
        return adapter.generate(
            messages=[{"role": "user", "content": str(prompt)}],
            system_prompt=system,
            cancel_event=task.cancel_event,
        )

    @staticmethod
    def _format_result_content(result: Any) -> str:
        """Format arbitrary result into natural companion speech hint."""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if "speech_summary" in result:
                return str(result["speech_summary"])
            if "content" in result:
                return str(result["content"])
            if "answer" in result:
                return str(result["answer"])
            return str(result)
        return str(result)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or running background task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.cancel_event.set()
            task.status = BackgroundTaskState.CANCELLED
            task.finished_at = time.time()
            fut = self._futures.get(task_id)
            if fut and not fut.done():
                fut.cancel()
            return True

    def cancel_all(self) -> int:
        """Cancel all pending or running background tasks."""
        cancelled = 0
        with self._lock:
            for task_id, task in self._tasks.items():
                if task.status in (BackgroundTaskState.PENDING, BackgroundTaskState.RUNNING):
                    task.cancel_event.set()
                    task.status = BackgroundTaskState.CANCELLED
                    task.finished_at = time.time()
                    fut = self._futures.get(task_id)
                    if fut and not fut.done():
                        fut.cancel()
                    cancelled += 1
        return cancelled

    def get_task(self, task_id: str) -> BackgroundTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, status: BackgroundTaskState | None = None) -> list[BackgroundTask]:
        with self._lock:
            tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def shutdown(self, wait: bool = False) -> None:
        self.cancel_all()
        self.executor.shutdown(wait=wait)


class MossCoordinationLayer:
    """Master orchestrator for the MOSS-Live foreground/background duplex architecture."""

    def __init__(
        self,
        registry: ModelSlotRegistry | None = None,
        duplex_arbiter: DuplexCascadeArbiter | None = None,
        min_silence_sec: float = 0.45,
        max_continuity_records: int = 5,
        bg_workers: int = 4,
        *,
        slot_registry: ModelSlotRegistry | None = None,
    ) -> None:
        self.registry = registry or slot_registry or ModelSlotRegistry()
        self.duplex_arbiter = duplex_arbiter or DuplexCascadeArbiter()
        self.pause_queue = NaturalPauseInjectionQueue(min_silence_sec=min_silence_sec)
        self.continuity_buffer = TurnContinuityBuffer(max_records=max_continuity_records)
        self.foreground_lane = ForegroundLane(registry=self.registry)
        self.background_manager = BackgroundTaskManager(
            registry=self.registry,
            pause_queue=self.pause_queue,
            max_workers=bg_workers,
        )
        self._lock = threading.Lock()
        self._active_turn_id: str | None = None

    @property
    def generation_epoch(self) -> int:
        return self.duplex_arbiter.generation_epoch

    def handle_user_turn(
        self,
        user_utterance: str,
        context: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        on_token: Callable[[str], None] | None = None,
        auto_resume_continuity: bool = True,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Handle a new user turn with duplex continuity and pause injection checks."""
        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._active_turn_id = turn_id

        messages = list(context or [])
        resumption_note = ""
        if auto_resume_continuity and self.continuity_buffer.has_interruption():
            resumed_rec = self.continuity_buffer.pop_resumption()
            if resumed_rec and resumed_rec.unspoken_text:
                resumption_note = (
                    f"\n[Контекст: ранее прерванная мысль: \"{resumed_rec.unspoken_text}\"]"
                )

        full_user_content = user_utterance + resumption_note
        messages.append({"role": "user", "content": full_user_content})

        cancel_ev = threading.Event()
        return self.foreground_lane.stream_turn(
            turn_id=turn_id,
            messages=messages,
            system_prompt=system_prompt,
            cancel_event=cancel_ev,
            on_token=on_token,
            **kwargs,
        )

    def handle_barge_in(
        self,
        user_utterance: str,
        spoken_prefix: str = "",
        full_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, TurnInterruptionRecord | None]:
        """Evaluate user speech against active assistant speech.

        Returns (is_interrupted, interruption_record).
        If user utterance is a brief backchannel (e.g., 'угу', 'да'), returns (False, None)
        and preserves playback.
        If substantive interruption, cancels generation, advances generation epoch,
        and saves unspoken portion to continuity buffer.
        """
        # 1. Backchannel check
        if is_user_backchannel(user_utterance):
            return False, None

        # 2. Substantive interruption -> cancel active lane
        spoken, unspoken = self.foreground_lane.cancel_current()

        # If explicit prefix/full passed from TTS layer, use those for higher precision
        effective_spoken = spoken_prefix or spoken
        effective_unspoken = (
            full_text[len(effective_spoken):] if len(full_text) > len(effective_spoken) else unspoken
        )

        # Monotonically advance epoch to invalidate in-flight TTS chunks
        self.duplex_arbiter.next_epoch()

        record = None
        turn_id = self._active_turn_id or f"turn_{uuid.uuid4().hex[:8]}"
        if effective_unspoken.strip():
            record = self.continuity_buffer.push_interruption(
                turn_id=turn_id,
                original_prompt="",
                spoken_text=effective_spoken,
                unspoken_text=effective_unspoken,
                user_barge_in_text=user_utterance,
                metadata=metadata or {},
            )

        return True, record

    def on_vad_silence(
        self,
        silence_elapsed_sec: float,
        assistant_speaking: bool = False,
        max_items: int = 1,
    ) -> list[NaturalPauseInjectionItem]:
        """Check and drain pending background injections during natural speech pause."""
        return self.pause_queue.drain_injectable(
            silence_elapsed_sec=silence_elapsed_sec,
            is_assistant_speaking=assistant_speaking,
            max_items=max_items,
        )

    def dispatch_background_task(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        priority: int = 10,
        runner_fn: Callable[[BackgroundTask], Any] | None = None,
        auto_inject: bool = True,
    ) -> BackgroundTask:
        """Dispatch asynchronous background cognitive task."""
        if payload is None:
            actual_type = "reasoning"
            actual_payload = {"prompt": task_type}
        else:
            actual_type = task_type
            actual_payload = payload
        return self.background_manager.submit_task(
            task_type=actual_type,
            payload=actual_payload,
            priority=priority,
            runner_fn=runner_fn,
            auto_inject=auto_inject,
        )

    def get_state_snapshot(self) -> dict[str, Any]:
        """Full duplex diagnostic snapshot."""
        return {
            "generation_epoch": self.generation_epoch,
            "active_turn_id": self._active_turn_id,
            "is_foreground_streaming": self.foreground_lane.is_streaming,
            "pause_queue_depth": len(self.pause_queue),
            "pause_queue_items": self.pause_queue.snapshot(),
            "continuity_records": self.continuity_buffer.snapshot(),
            "has_pending_continuity": self.continuity_buffer.has_interruption(),
            "background_tasks": [t.to_dict() for t in self.background_manager.list_tasks()],
        }

    def shutdown(self) -> None:
        """Gracefully release threads and queues."""
        self.background_manager.shutdown(wait=False)
        self.pause_queue.clear()
        self.continuity_buffer.clear()
