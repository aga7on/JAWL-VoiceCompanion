"""Unit tests for pluggable ModelSlot, ModelAdapter, and ModelSlotRegistry."""

import json
import threading
from io import BytesIO
from typing import Any
import pytest

from jawl_voicecompanion.model_slots import (
    LlamaServerAdapter,
    MockModelAdapter,
    ModelAdapter,
    ModelAdapterError,
    ModelCancelled,
    ModelCapabilities,
    ModelSlot,
    ModelSlotRegistry,
    ModelUnavailable,
    OpenAICompatibleAdapter,
    SlotNotFound,
    SlotRefAdapter,
    _extract_tool_calls_from_text,
)


def test_model_slot_enum() -> None:
    assert ModelSlot.from_str("foreground_brain") == ModelSlot.FOREGROUND_BRAIN
    assert ModelSlot.from_str("BACKGROUND_REASONER") == ModelSlot.BACKGROUND_REASONER
    assert ModelSlot.from_str(ModelSlot.VISION_PERCEPTION) == ModelSlot.VISION_PERCEPTION
    with pytest.raises(ValueError):
        ModelSlot.from_str("invalid_role")


def test_model_capabilities_serialization() -> None:
    caps = ModelCapabilities(
        supports_streaming=True,
        supports_tools=False,
        supports_vision=True,
        context_window=16384,
        model_name="test-llm",
    )
    d = caps.to_dict()
    assert d["supports_streaming"] is True
    assert d["supports_tools"] is False
    assert d["supports_vision"] is True
    assert d["context_window"] == 16384
    assert d["model_name"] == "test-llm"

    restored = ModelCapabilities.from_dict(d)
    assert restored.model_name == "test-llm"
    assert restored.supports_vision is True


def test_mock_adapter_generate_and_cancellation() -> None:
    adapter = MockModelAdapter(
        default_response="Default answer",
        canned_responses={"weather": "It is sunny today."},
    )
    # Basic generation
    assert adapter.generate("What is the weather?") == "It is sunny today."
    assert adapter.generate("Hello there") == "Default answer"
    assert len(adapter.call_log) == 2

    # Cancellation
    cancel_evt = threading.Event()
    cancel_evt.set()
    with pytest.raises(ModelCancelled):
        adapter.generate("Hello", cancel_event=cancel_evt)


def test_mock_adapter_streaming() -> None:
    adapter = MockModelAdapter(default_response="One two three four")
    chunks = list(adapter.stream_generate("prompt"))
    assert "".join(chunks).strip() == "One two three four"

    # Streaming cancellation
    cancel_evt = threading.Event()
    cancel_evt.set()
    with pytest.raises(ModelCancelled):
        list(adapter.stream_generate("prompt", cancel_event=cancel_evt))


def test_mock_adapter_canned_tool_calls() -> None:
    adapter = MockModelAdapter(
        canned_tool_calls={
            "search": [{"name": "web_search", "arguments": {"query": "pytest"}}]
        }
    )
    res = adapter.generate_with_tools("Please search for JAWL", tools=[{"name": "web_search"}])
    assert res["finish_reason"] == "tool_calls"
    assert len(res["tool_calls"]) == 1
    assert res["tool_calls"][0]["name"] == "web_search"
    assert res["tool_calls"][0]["arguments"] == {"query": "pytest"}


def test_fallback_streaming_emulation() -> None:
    class NonStreamingAdapter(ModelAdapter):
        def generate(self, prompt: str, **kwargs: Any) -> str:
            return "First sentence. Second sentence! Third sentence?"

        def health(self) -> dict[str, Any]:
            return {"status": "online"}

    adapter = NonStreamingAdapter("non_streaming", ModelCapabilities(supports_streaming=False))
    chunks = list(adapter.stream_generate("tell me"))
    reconstructed = "".join(chunks)
    assert "First sentence." in reconstructed
    assert "Second sentence!" in reconstructed
    assert len(chunks) >= 2


def test_extract_tool_calls_from_text() -> None:
    json_block = """Here is your answer:
```json
{"tool": "calculate", "arguments": {"x": 5, "y": 10}}
```
Hope that helps!"""
    calls = _extract_tool_calls_from_text(json_block)
    assert len(calls) == 1
    assert calls[0]["name"] == "calculate"
    assert calls[0]["arguments"] == {"x": 5, "y": 10}

    raw_json = 'I will execute {"function": "turn_light_on", "parameters": {"room": "kitchen"}}'
    calls2 = _extract_tool_calls_from_text(raw_json)
    assert len(calls2) == 1
    assert calls2[0]["name"] == "turn_light_on"
    assert calls2[0]["arguments"] == {"room": "kitchen"}


def test_fallback_tool_emulation() -> None:
    class PromptEchoAdapter(ModelAdapter):
        def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
            # Emulate an LLM responding with a ReAct markdown block
            return 'Thinking...\n```json\n{"tool": "get_time", "arguments": {"timezone": "UTC"}}\n```'

        def health(self) -> dict[str, Any]:
            return {"status": "online"}

    adapter = PromptEchoAdapter("no_tool_adapter", ModelCapabilities(supports_tools=False))
    tools = [{"name": "get_time", "description": "Returns current time", "parameters": {}}]
    res = adapter.generate_with_tools("What time is it?", tools=tools)

    assert res["finish_reason"] == "tool_calls"
    assert len(res["tool_calls"]) == 1
    assert res["tool_calls"][0]["name"] == "get_time"
    assert res["tool_calls"][0]["arguments"] == {"timezone": "UTC"}
    assert "Thinking..." in res["text"]


def test_fallback_vision_description() -> None:
    received_prompt = ""

    class VisionMock(ModelAdapter):
        def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
            nonlocal received_prompt
            received_prompt = prompt
            return "I see a start button and player avatar."

        def health(self) -> dict[str, Any]:
            return {"status": "online"}

    adapter = VisionMock("vision_text_bridge", ModelCapabilities(supports_vision=False))
    obs = {
        "entities": [{"label": "boss_dragon", "bbox": "[100, 200, 300, 400]", "attributes": "flying"}],
        "ocr_tokens": [{"text": "HP: 100/100", "bbox": "[10, 10, 50, 20]"}],
        "ui_elements": [{"name": "Start Button", "role": "button"}],
        "dominant_colors": ["crimson", "darkgray"],
    }
    desc = adapter.describe_vision(obs, prompt="What is the player's health?")
    assert "start button" in desc
    assert "boss_dragon" in received_prompt
    assert "HP: 100/100" in received_prompt
    assert "Start Button" in received_prompt
    assert "crimson" in received_prompt


def test_fallback_audio_analysis() -> None:
    received_prompt = ""

    class AudioMock(ModelAdapter):
        def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
            nonlocal received_prompt
            received_prompt = prompt
            return "Laughter detected in background."

        def health(self) -> dict[str, Any]:
            return {"status": "online"}

    adapter = AudioMock("audio_text_bridge", ModelCapabilities(supports_audio=False))
    feat = {
        "labels": ["giggle", "ambient_fan"],
        "paralinguistics": {"arousal": 0.8, "valence": 0.9},
        "energy": 0.045,
    }
    ans = adapter.analyze_audio(feat, prompt="Is user amused?")
    assert "Laughter" in ans
    assert "giggle" in received_prompt
    assert "arousal" in received_prompt


def test_slot_registry_and_swapping() -> None:
    registry = ModelSlotRegistry()
    primary = MockModelAdapter(name="primary_brain", default_response="Primary brain output")
    backup = MockModelAdapter(name="backup_brain", default_response="Backup brain output")

    registry.register(ModelSlot.FOREGROUND_BRAIN, primary, fallback=ModelSlot.BACKGROUND_REASONER)
    registry.register(ModelSlot.BACKGROUND_REASONER, backup)

    assert registry.has("foreground_brain")
    assert registry.has(ModelSlot.BACKGROUND_REASONER)
    assert not registry.has("coordinator")

    adapter = registry.get("foreground_brain")
    assert adapter.name == "primary_brain"
    assert adapter.generate("test") == "Primary brain output"

    # Capability verification
    assert registry.verify_capabilities(ModelSlot.FOREGROUND_BRAIN, {"supports_streaming"})
    assert not registry.verify_capabilities(
        ModelSlot.FOREGROUND_BRAIN, {"supports_streaming", "supports_fill_in_the_middle"}
    )

    # Hot swap
    replacement = MockModelAdapter(name="replacement_brain", default_response="Replacement brain output")
    old = registry.swap(ModelSlot.FOREGROUND_BRAIN, replacement)
    assert old.name == "primary_brain"
    assert registry.get(ModelSlot.FOREGROUND_BRAIN).name == "replacement_brain"

    # Fallback resolution
    replacement.is_healthy = False
    resolved = registry.get_with_fallback(ModelSlot.FOREGROUND_BRAIN)
    assert resolved.name == "backup_brain"

    # Snapshot check
    snap = registry.snapshot()
    assert "foreground_brain" in snap
    assert snap["foreground_brain"]["adapter_name"] == "replacement_brain"


def test_slot_ref_adapter() -> None:
    registry = ModelSlotRegistry()
    shared = MockModelAdapter(
        name="shared_loop_9b",
        default_response="SenseNova output",
        capabilities=ModelCapabilities(context_window=32768, supports_tools=True),
    )
    registry.register(ModelSlot.FOREGROUND_BRAIN, shared)

    # Reference foreground slot for background role
    ref_adapter = SlotRefAdapter(
        name="background_via_shared",
        registry=registry,
        target_slot=ModelSlot.FOREGROUND_BRAIN,
        system_prompt_override="System: act as background planner",
    )

    assert ref_adapter.capabilities.context_window == 32768
    out = ref_adapter.generate("Plan task")
    assert out == "SenseNova output"
    assert shared.call_log[-1]["system_prompt"] == "System: act as background planner"

    health = ref_adapter.health()
    assert health["status"] == "online"
    assert health["target_adapter"] == "shared_loop_9b"


class DummyHttpResponse:
    def __init__(self, data: bytes, code: int = 200) -> None:
        self._bio = BytesIO(data)
        self.code = code

    def read(self, amt: int | None = None) -> bytes:
        return self._bio.read(amt)

    def __iter__(self):
        return iter(self._bio)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_openai_compatible_adapter_mock_http() -> None:
    response_body = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "Hello from mock HTTP"}}]
    }).encode("utf-8")

    def mock_opener(req: Any, timeout: float = 60.0) -> DummyHttpResponse:
        return DummyHttpResponse(response_body)

    adapter = OpenAICompatibleAdapter(
        name="test_openai",
        endpoint="http://127.0.0.1:8990/v1",
        model="test-model",
        opener=mock_opener,
    )

    assert adapter.endpoint == "http://127.0.0.1:8990/v1/chat/completions"
    res = adapter.generate("hi")
    assert res == "Hello from mock HTTP"


def test_openai_compatible_adapter_streaming_mock_http() -> None:
    sse_body = (
        b'data: {"choices":[{"delta":{"content":"Chunk 1 "}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"Chunk 2"}}]}\n\n'
        b'data: [DONE]\n\n'
    )

    def mock_opener(req: Any, timeout: float = 60.0) -> DummyHttpResponse:
        return DummyHttpResponse(sse_body)

    adapter = OpenAICompatibleAdapter(
        name="test_openai_stream",
        endpoint="http://127.0.0.1:8990/v1",
        model="test-model",
        opener=mock_opener,
    )

    tokens = list(adapter.stream_generate("hi"))
    assert tokens == ["Chunk 1 ", "Chunk 2"]


def test_llama_server_adapter_slots() -> None:
    slots_json = json.dumps([{"id": 0, "state": 1, "is_processing": True}]).encode("utf-8")

    def mock_opener(req: Any, timeout: float = 2.0) -> DummyHttpResponse:
        return DummyHttpResponse(slots_json)

    adapter = LlamaServerAdapter(
        name="llama_server",
        endpoint="http://127.0.0.1:8990",
        opener=mock_opener,
    )
    slots = adapter.get_server_slots()
    assert len(slots) == 1
    assert slots[0]["id"] == 0
    assert slots[0]["is_processing"] is True
