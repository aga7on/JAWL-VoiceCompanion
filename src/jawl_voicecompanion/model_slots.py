"""Pluggable model role framework for JAWL VoiceCompanion.

Implements model-agnostic slots, capability negotiation, fallback emulation
(streaming chunking, ReAct JSON tool wrappers, text vision/audio bridges),
and adapters for llama-server, OpenAI-compatible APIs, slot references, and mocks.
"""

from __future__ import annotations

import abc
import enum
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelSlot(str, enum.Enum):
    """Interchangeable cognitive role slots in JAWL."""

    FOREGROUND_BRAIN = "foreground_brain"
    BACKGROUND_REASONER = "background_reasoner"
    VISION_PERCEPTION = "vision_perception"
    AUDIO_PERCEPTION = "audio_perception"
    COORDINATOR = "coordinator"
    GAME_EMBODIMENT = "game_embodiment"

    @classmethod
    def from_str(cls, value: str | ModelSlot) -> ModelSlot:
        if isinstance(value, ModelSlot):
            return value
        clean = str(value or "").strip().lower()
        for slot in cls:
            if slot.value == clean or slot.name.lower() == clean:
                return slot
        raise ValueError(f"Unknown model slot: {value}")


@dataclass
class ModelCapabilities:
    """Declared and negotiated model capabilities."""

    supports_streaming: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    supports_json_schema: bool = True
    supports_fill_in_the_middle: bool = False
    context_window: int = 8192
    max_output_tokens: int = 1024
    model_name: str = ""
    provider_type: str = "generic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelCapabilities:
        valid_fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


class ModelAdapterError(RuntimeError):
    """Base error for model adapter operations."""


class ModelUnavailable(ModelAdapterError):
    """The configured model provider is unreachable or returned an error."""


class ModelCancelled(ModelAdapterError):
    """The generation was cancelled by a newer turn or user interruption."""


class SlotNotFound(KeyError):
    """The requested model slot is not registered."""


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


def _find_json_objects(text: str) -> list[dict[str, Any]]:
    """Find all top-level valid JSON objects within arbitrary text."""
    results: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            depth = 0
            in_str = False
            escape = False
            start = i
            end = -1
            for j in range(i, n):
                char = text[j]
                if escape:
                    escape = False
                    continue
                if char == "\\":
                    escape = True
                    continue
                if char == '"':
                    in_str = not in_str
                    continue
                if not in_str:
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            end = j + 1
                            break
            if end != -1:
                candidate = text[start:end]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        results.append(obj)
                        i = end
                        continue
                except Exception:
                    pass
        i += 1
    return results


def _extract_tool_calls_from_text(text: str) -> list[dict[str, Any]]:
    """Robustly parse ReAct JSON tool calls from free text."""
    results: list[dict[str, Any]] = []

    # First attempt: Markdown code blocks with json
    for match in _JSON_BLOCK_RE.finditer(text):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and ("tool" in parsed or "name" in parsed or "function" in parsed):
                name = parsed.get("tool") or parsed.get("name") or parsed.get("function")
                args = parsed.get("arguments") or parsed.get("parameters") or parsed.get("args") or {}
                results.append({"name": str(name), "arguments": args if isinstance(args, dict) else {}})
        except (json.JSONDecodeError, ValueError):
            continue

    if results:
        return results

    # Second attempt: Raw JSON object containing tool or function key
    for obj in _find_json_objects(text):
        if "tool" in obj or "name" in obj or "function" in obj:
            name = obj.get("tool") or obj.get("name") or obj.get("function")
            args = obj.get("arguments") or obj.get("parameters") or obj.get("args") or {}
            results.append({"name": str(name), "arguments": args if isinstance(args, dict) else {}})

    return results


def _clean_tool_text(raw_text: str, tool_calls: list[dict[str, Any]]) -> str:
    """Strip out markdown json blocks if they represent tool calls, leaving commentary."""
    clean = _JSON_BLOCK_RE.sub("", raw_text).strip()
    return clean


class ModelAdapter(abc.ABC):
    """Abstract base class for pluggable model adapters with fallback emulation."""

    def __init__(self, name: str, capabilities: ModelCapabilities | None = None) -> None:
        self.name = str(name or "unnamed_adapter").strip()
        self.capabilities = capabilities or ModelCapabilities()

    @abc.abstractmethod
    def generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Synchronously generate a completion."""

    def stream_generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream generated tokens.

        Fallback: If adapter does not implement native streaming, wraps generate()
        and chunks text into small sentence/phrase pieces.
        """
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Generation cancelled before start")

        full_text = self.generate(
            prompt=prompt,
            messages=messages,
            system_prompt=system_prompt,
            cancel_event=cancel_event,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        # Chunk the output into phrase-sized slices
        delimiters = re.compile(r"([.!?,\n]+)")
        parts = delimiters.split(full_text)
        current = ""
        for part in parts:
            if cancel_event is not None and cancel_event.is_set():
                raise ModelCancelled("Generation cancelled during fallback streaming")
            current += part
            if len(current) >= 15 or part in {".", "!", "?", "\n"}:
                yield current
                current = ""
        if current:
            yield current

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        *,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate with tool invocation capability.

        Fallback: If model does not natively support tools, synthesizes a ReAct prompt
        wrapper and parses JSON blocks.
        """
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Tool generation cancelled before start")

        # Fallback ReAct prompt wrapper
        tool_descriptions = []
        for t in tools:
            name = t.get("name", "unknown")
            desc = t.get("description", "")
            params = t.get("parameters", {})
            tool_descriptions.append(f"- Tool: `{name}`: {desc}. Parameters: {json.dumps(params, ensure_ascii=False)}")

        tool_guide = (
            "\n\nYou have access to the following background tools:\n"
            + "\n".join(tool_descriptions)
            + "\n\nIf you need to call a tool, respond with ONLY a JSON markdown block:\n"
            + "```json\n"
            + '{"tool": "<tool_name>", "arguments": {<parameters>}}\n'
            + "```\n"
            + "If no tool is needed, respond directly with your answer."
        )

        effective_system = (system_prompt or "") + tool_guide
        response_text = self.generate(
            prompt,
            system_prompt=effective_system,
            cancel_event=cancel_event,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        parsed_calls = _extract_tool_calls_from_text(response_text)
        clean_text = _clean_tool_text(response_text, parsed_calls)

        return {
            "text": clean_text,
            "tool_calls": parsed_calls,
            "finish_reason": "tool_calls" if parsed_calls else "stop",
            "raw_response": response_text,
        }

    def describe_vision(
        self,
        observation: dict[str, Any],
        prompt: str = "Describe what is on screen",
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Describe visual state.

        Fallback: Converts structured observation (OCR tokens, bounding boxes, entities)
        into a dense text context and queries the text model.
        """
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Vision description cancelled")

        lines = ["[Visual Scene Observation]"]
        entities = observation.get("entities") or []
        if entities:
            lines.append("Detected entities:")
            for e in entities[:15]:
                label = e.get("label", "unknown")
                bbox = e.get("bbox") or e.get("box") or ""
                attr = e.get("attributes") or ""
                lines.append(f" - {label} (box={bbox}, attr={attr})")

        ocr_tokens = observation.get("ocr_tokens") or []
        if ocr_tokens:
            lines.append("Detected text/OCR on screen:")
            for tok in ocr_tokens[:30]:
                text = tok.get("text") or tok.get("string") or str(tok)
                loc = tok.get("bbox") or tok.get("location") or ""
                lines.append(f" - \"{text}\" at {loc}")

        ui_elements = observation.get("ui_elements") or []
        if ui_elements:
            lines.append("UI Elements:")
            for ui in ui_elements[:15]:
                name = ui.get("name") or ui.get("text") or ""
                role = ui.get("role") or "control"
                lines.append(f" - [{role}] {name}")

        colors = observation.get("dominant_colors") or []
        if colors:
            lines.append(f"Dominant colors: {', '.join(str(c) for c in colors[:5])}")

        dense_prompt = "\n".join(lines) + f"\n\nQuestion/Task: {prompt}"
        return self.generate(
            dense_prompt,
            system_prompt="You are a multimodal perception interpreter. Summarize visual details accurately.",
            cancel_event=cancel_event,
        )

    def analyze_audio(
        self,
        features: dict[str, Any],
        prompt: str = "Analyze the acoustic environment",
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Analyze acoustic scene.

        Fallback: Converts acoustic tags and paralinguistics into structured text.
        """
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Audio analysis cancelled")

        lines = ["[Audio Scene Observation]"]
        labels = features.get("labels") or features.get("tags") or []
        if labels:
            lines.append(f"Acoustic tags: {', '.join(str(lbl) for lbl in labels)}")
        paralinguistics = features.get("paralinguistics") or {}
        if paralinguistics:
            lines.append(f"Paralinguistics: {json.dumps(paralinguistics, ensure_ascii=False)}")
        energy = features.get("energy") or features.get("rms")
        if energy is not None:
            lines.append(f"Energy/RMS: {energy}")

        dense_prompt = "\n".join(lines) + f"\n\nQuestion/Task: {prompt}"
        return self.generate(
            dense_prompt,
            system_prompt="You are an acoustic scene analyst. Accurately infer paralinguistic tone and ambient events.",
            cancel_event=cancel_event,
        )

    @abc.abstractmethod
    def health(self) -> dict[str, Any]:
        """Check provider connectivity and status."""


class MockModelAdapter(ModelAdapter):
    """Deterministic mock adapter for testing, unit tests, and offline development."""

    def __init__(
        self,
        name: str = "mock_model",
        capabilities: ModelCapabilities | None = None,
        default_response: str = "Mock response",
        canned_responses: dict[str, str] | list[str] | None = None,
        canned_tool_calls: dict[str, list[dict[str, Any]]] | None = None,
        is_healthy: bool = True,
        *,
        model_name: str | None = None,
    ) -> None:
        model_label = model_name or (capabilities.model_name if capabilities else "mock-v1")
        adapter_name = name if name != "mock_model" else (model_name or name)
        caps = capabilities or ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
            supports_audio=True,
            model_name=model_label,
            provider_type="mock",
        )
        super().__init__(name=adapter_name, capabilities=caps)
        self.default_response = default_response
        if isinstance(canned_responses, list):
            self.canned_responses = {str(item): str(item) for item in canned_responses}
            if canned_responses and default_response == "Mock response":
                self.default_response = str(canned_responses[0])
        elif isinstance(canned_responses, dict):
            self.canned_responses = dict(canned_responses)
        else:
            self.canned_responses = {}
        self.canned_tool_calls = dict(canned_tool_calls or {})
        self.is_healthy = is_healthy
        self.call_log: list[dict[str, Any]] = []

    def generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Mock generation cancelled")
        effective_prompt = prompt
        if not effective_prompt and messages:
            effective_prompt = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
        self.call_log.append({
            "method": "generate",
            "prompt": effective_prompt,
            "messages": messages,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "kwargs": kwargs,
        })
        for pattern, answer in self.canned_responses.items():
            if pattern in effective_prompt:
                return answer
        return self.default_response

    def stream_generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Mock stream cancelled before start")
        text = self.generate(
            prompt=prompt,
            messages=messages,
            system_prompt=system_prompt,
            cancel_event=cancel_event,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        words = text.split(" ")
        for i, word in enumerate(words):
            if cancel_event is not None and cancel_event.is_set():
                raise ModelCancelled("Mock stream cancelled during iteration")
            suffix = " " if i < len(words) - 1 else ""
            yield word + suffix
    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        *,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Mock tool call cancelled")
        self.call_log.append({
            "method": "generate_with_tools",
            "prompt": prompt,
            "tools": tools,
            "system_prompt": system_prompt,
        })
        for pattern, calls in self.canned_tool_calls.items():
            if pattern in prompt:
                return {
                    "text": "Invoking requested tool",
                    "tool_calls": calls,
                    "finish_reason": "tool_calls",
                }
        if not self.capabilities.supports_tools:
            # Exercise fallback path
            return super().generate_with_tools(
                prompt,
                tools,
                system_prompt=system_prompt,
                cancel_event=cancel_event,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        return {
            "text": self.generate(prompt, system_prompt=system_prompt, cancel_event=cancel_event),
            "tool_calls": [],
            "finish_reason": "stop",
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "online" if self.is_healthy else "offline",
            "adapter": self.name,
            "model": self.capabilities.model_name,
            "calls_recorded": len(self.call_log),
        }


class OpenAICompatibleAdapter(ModelAdapter):
    """Universal adapter for OpenAI-compatible HTTP endpoints (vLLM, Ollama, LMStudio, etc.)."""

    def __init__(
        self,
        name: str,
        endpoint: str,
        model: str,
        *,
        api_key: str = "",
        timeout_seconds: float = 60.0,
        capabilities: ModelCapabilities | None = None,
        user_agent: str = "JAWL-ModelAdapter/1.0",
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        caps = capabilities or ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            model_name=model,
            provider_type="openai_compatible",
        )
        super().__init__(name=name, capabilities=caps)
        self.raw_endpoint = str(endpoint or "").strip().rstrip("/")
        if not self.raw_endpoint:
            raise ValueError("Endpoint URL is required")
        if self.raw_endpoint.endswith("/chat/completions"):
            self.endpoint = self.raw_endpoint
        elif self.raw_endpoint.endswith("/v1"):
            self.endpoint = f"{self.raw_endpoint}/chat/completions"
        else:
            self.endpoint = f"{self.raw_endpoint}/v1/chat/completions"

        self.model = str(model or "").strip()
        self.api_key = str(api_key or "")
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self.user_agent = user_agent
        self._opener = opener

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health(self) -> dict[str, Any]:
        models_url = self.endpoint.replace("/chat/completions", "/models")
        req = Request(models_url, headers=self._headers(), method="GET")
        try:
            with self._opener(req, timeout=min(5.0, self.timeout_seconds)) as resp:
                data = json.loads(resp.read(64 * 1024).decode("utf-8"))
            return {
                "status": "online",
                "model": self.model,
                "endpoint": self.endpoint,
                "models_available": isinstance(data, dict),
            }
        except Exception as exc:
            return {
                "status": "offline",
                "model": self.model,
                "endpoint": self.endpoint,
                "error": str(exc),
            }

    def generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Request cancelled before dispatch")

        req_messages: list[dict[str, Any]] = list(messages) if messages is not None else []
        if not req_messages:
            if system_prompt:
                req_messages.append({"role": "system", "content": system_prompt})
            if prompt:
                req_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": req_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.capabilities.max_output_tokens,
        }
        req = Request(self.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=self._headers(), method="POST")

        try:
            with self._opener(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read(512 * 1024).decode("utf-8"))
        except HTTPError as exc:
            raise ModelUnavailable(f"HTTP {exc.code} from {self.endpoint}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise ModelUnavailable(f"Connection failure to {self.endpoint}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ModelUnavailable("Invalid JSON received from endpoint") from exc

        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Request cancelled after dispatch")

        choices = data.get("choices") or []
        if not choices:
            raise ModelUnavailable("No choices returned from model")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        return content.strip()

    def stream_generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        if not self.capabilities.supports_streaming:
            yield from super().stream_generate(
                prompt=prompt,
                messages=messages,
                system_prompt=system_prompt,
                cancel_event=cancel_event,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return

        if cancel_event is not None and cancel_event.is_set():
            raise ModelCancelled("Stream cancelled before dispatch")

        req_messages: list[dict[str, Any]] = list(messages) if messages is not None else []
        if not req_messages:
            if system_prompt:
                req_messages.append({"role": "system", "content": system_prompt})
            if prompt:
                req_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": req_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.capabilities.max_output_tokens,
            "stream": True,
        }
        headers = {**self._headers(), "Accept": "text/event-stream"}
        req = Request(self.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")

        try:
            with self._opener(req, timeout=self.timeout_seconds) as resp:
                for raw_line in resp:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ModelCancelled("Stream cancelled by caller")
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    data_str = line[5:].strip() if line.startswith("data:") else line
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_obj = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk_obj.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content
        except HTTPError as exc:
            raise ModelUnavailable(f"Stream HTTP {exc.code} from {self.endpoint}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise ModelUnavailable(f"Stream connection failure to {self.endpoint}: {exc}") from exc


class LlamaServerAdapter(OpenAICompatibleAdapter):
    """Adapter optimized for llama.cpp server (SenseNova Loop 9B Preview, etc.).

    Provides slot monitoring (/slots) and health probes.
    """

    def __init__(
        self,
        name: str = "sensenova_loop_adapter",
        endpoint: str = "http://127.0.0.1:8990",
        model: str = "SenseNova-Loop-9B-Preview",
        *,
        timeout_seconds: float = 60.0,
        capabilities: ModelCapabilities | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        caps = capabilities or ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_vision=False,
            supports_audio=False,
            supports_json_schema=True,
            context_window=32768,
            max_output_tokens=2048,
            model_name=model,
            provider_type="llama_server",
        )
        super().__init__(
            name=name,
            endpoint=endpoint,
            model=model,
            timeout_seconds=timeout_seconds,
            capabilities=caps,
            user_agent="JAWL-LlamaServerAdapter/1.0",
            opener=opener,
        )
        self.base_url = self.raw_endpoint.replace("/v1", "").replace("/chat/completions", "")

    def get_server_slots(self) -> list[dict[str, Any]]:
        """Query llama-server /slots to inspect active KV cache & execution state."""
        slots_url = f"{self.base_url}/slots"
        req = Request(slots_url, headers={"User-Agent": self.user_agent}, method="GET")
        try:
            with self._opener(req, timeout=2.0) as resp:
                data = json.loads(resp.read(64 * 1024).decode("utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def health(self) -> dict[str, Any]:
        health_url = f"{self.base_url}/health"
        req = Request(health_url, headers={"User-Agent": self.user_agent}, method="GET")
        try:
            with self._opener(req, timeout=2.0) as resp:
                data = json.loads(resp.read(16 * 1024).decode("utf-8"))
            slots = self.get_server_slots()
            return {
                "status": "online" if data.get("status") in {"ok", "loading model"} else "online",
                "model": self.model,
                "slots_count": len(slots),
                "server_health": data,
            }
        except Exception as exc:
            # Fallback to standard OpenAI /models endpoint probe
            return super().health()


class SlotRefAdapter(ModelAdapter):
    """Virtual alias adapter referencing another slot in a registry.

    Allows sharing a single engine (e.g. SenseNova Loop 9B) between foreground
    and background roles while maintaining separate system prompts and parameters.
    """

    def __init__(
        self,
        name: str,
        registry: ModelSlotRegistry,
        target_slot: ModelSlot | str,
        *,
        system_prompt_override: str | None = None,
        temperature_override: float | None = None,
    ) -> None:
        self.registry = registry
        self.target_slot = ModelSlot.from_str(target_slot)
        self.system_prompt_override = system_prompt_override
        self.temperature_override = temperature_override
        super().__init__(name=name, capabilities=ModelCapabilities())

    def _target(self) -> ModelAdapter:
        return self.registry.get(self.target_slot)

    @property
    def capabilities(self) -> ModelCapabilities:  # type: ignore[override]
        target = self.registry.get(self.target_slot)
        return target.capabilities

    @capabilities.setter
    def capabilities(self, value: ModelCapabilities) -> None:
        pass

    def generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        eff_system = self.system_prompt_override if self.system_prompt_override is not None else system_prompt
        eff_temp = self.temperature_override if self.temperature_override is not None else temperature
        return self._target().generate(
            prompt=prompt,
            messages=messages,
            system_prompt=eff_system,
            cancel_event=cancel_event,
            temperature=eff_temp,
            max_tokens=max_tokens,
            **kwargs,
        )

    def stream_generate(
        self,
        prompt: str = "",
        *,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        eff_system = self.system_prompt_override if self.system_prompt_override is not None else system_prompt
        eff_temp = self.temperature_override if self.temperature_override is not None else temperature
        return self._target().stream_generate(
            prompt=prompt,
            messages=messages,
            system_prompt=eff_system,
            cancel_event=cancel_event,
            temperature=eff_temp,
            max_tokens=max_tokens,
            **kwargs,
        )

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        *,
        system_prompt: str | None = None,
        cancel_event: threading.Event | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        eff_system = self.system_prompt_override if self.system_prompt_override is not None else system_prompt
        eff_temp = self.temperature_override if self.temperature_override is not None else temperature
        return self._target().generate_with_tools(
            prompt,
            tools,
            system_prompt=eff_system,
            cancel_event=cancel_event,
            temperature=eff_temp,
            max_tokens=max_tokens,
            **kwargs,
        )

    def describe_vision(
        self,
        observation: dict[str, Any],
        prompt: str = "Describe what is on screen",
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        return self._target().describe_vision(observation, prompt=prompt, cancel_event=cancel_event)

    def analyze_audio(
        self,
        features: dict[str, Any],
        prompt: str = "Analyze the acoustic environment",
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        return self._target().analyze_audio(features, prompt=prompt, cancel_event=cancel_event)

    def health(self) -> dict[str, Any]:
        target_health = self._target().health()
        return {
            "status": target_health.get("status", "unknown"),
            "slot_ref": self.target_slot.value,
            "target_adapter": self._target().name,
            "details": target_health,
        }


class ModelSlotRegistry:
    """Thread-safe registry for interchangeable model slots with capability negotiation."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._slots: dict[ModelSlot, ModelAdapter] = {}
        self._fallbacks: dict[ModelSlot, ModelSlot] = {}

    def register(
        self,
        slot: ModelSlot | str,
        adapter: ModelAdapter,
        *,
        fallback: ModelSlot | str | None = None,
    ) -> None:
        """Register an adapter for a cognitive slot."""
        slot_enum = ModelSlot.from_str(slot)
        with self._lock:
            self._slots[slot_enum] = adapter
            if fallback is not None:
                self._fallbacks[slot_enum] = ModelSlot.from_str(fallback)

    def get(self, slot: ModelSlot | str) -> ModelAdapter:
        """Retrieve the adapter for a slot. Raises SlotNotFound if missing."""
        slot_enum = ModelSlot.from_str(slot)
        with self._lock:
            adapter = self._slots.get(slot_enum)
            if adapter is None:
                raise SlotNotFound(f"Model slot '{slot_enum.value}' is not registered")
            return adapter

    def get_with_fallback(self, slot: ModelSlot | str) -> ModelAdapter:
        """Retrieve slot adapter, smoothly resolving to fallback if primary is missing or unhealthy."""
        slot_enum = ModelSlot.from_str(slot)
        with self._lock:
            adapter = self._slots.get(slot_enum)
            if adapter is not None:
                try:
                    h = adapter.health()
                    if h.get("status") == "online":
                        return adapter
                except Exception:
                    pass
            # Try fallback
            fb_slot = self._fallbacks.get(slot_enum)
            if fb_slot and fb_slot in self._slots:
                return self._slots[fb_slot]
            if adapter is not None:
                return adapter
            raise SlotNotFound(f"No active or fallback adapter for slot '{slot_enum.value}'")

    def swap(self, slot: ModelSlot | str, new_adapter: ModelAdapter) -> ModelAdapter:
        """Hot-swap the adapter in a slot and return the previous adapter."""
        slot_enum = ModelSlot.from_str(slot)
        with self._lock:
            old = self.get(slot_enum)
            self._slots[slot_enum] = new_adapter
            return old

    def has(self, slot: ModelSlot | str) -> bool:
        slot_enum = ModelSlot.from_str(slot)
        with self._lock:
            return slot_enum in self._slots

    def verify_capabilities(self, slot: ModelSlot | str, required: set[str]) -> bool:
        """Check if registered slot meets required capabilities."""
        adapter = self.get(slot)
        caps = adapter.capabilities
        for req in required:
            if not getattr(caps, req, False):
                return False
        return True

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a structured overview of all registered slots, health, and capabilities."""
        with self._lock:
            res: dict[str, dict[str, Any]] = {}
            for slot_enum, adapter in self._slots.items():
                try:
                    h = adapter.health()
                except Exception as exc:
                    h = {"status": "error", "error": str(exc)}
                res[slot_enum.value] = {
                    "adapter_name": adapter.name,
                    "model_name": adapter.capabilities.model_name,
                    "provider_type": adapter.capabilities.provider_type,
                    "health": h,
                    "capabilities": adapter.capabilities.to_dict(),
                    "fallback": self._fallbacks.get(slot_enum).value if self._fallbacks.get(slot_enum) else None,
                }
            return res
