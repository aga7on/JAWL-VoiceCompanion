"""Bind correlated Companion delivery requirements into native JAWL context.

The provider is intentionally small and contains no user supplied text. It is
registered on each builder's native ContextRegistry before the original
ContextBuilder.build runs, so normal native ordering and context compaction
remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import re
from threading import RLock
from typing import Any, Callable


_PROVIDER_NAME = "jawl_companion_turn_binding"
_INSTALL_ATTR = "__jawl_native_turn_context_installation__"
_SAFE_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_BINDING_TEXT = (
    "## ACTIVE COMPANION TURN\n"
    "This is the same active user turn. HEARTBEAT here is an internal step, "
    "not a background request. A terminal delivery is still required. "
    "If this turn has already been delivered, do not send it again."
)
_REGISTRATION_LOCK = RLock()


def _valid_turn_id(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_TURN_ID.fullmatch(value):
        return ""
    return value


@dataclass(frozen=True)
class NativeTurnContextInstallation:
    """Handle for the owned ContextBuilder.build wrapper."""

    context_builder_class: type
    context_section: Any
    current_turn_id: Callable[[], Any]
    original_build: Callable[..., Any]
    wrapped_build: Callable[..., Any]


def _load_native_api() -> tuple[type, Any, Callable[[], Any]]:
    registry_module = importlib.import_module("src.l3_agent.context.registry")
    builder_module = importlib.import_module("src.l3_agent.context.builder")
    gateway_module = importlib.import_module("src.l3_agent.companion_gateway")
    return (
        builder_module.ContextBuilder,
        registry_module.ContextSection.INTERFACES,
        gateway_module.current_companion_turn_id,
    )


def install_native_jawl_turn_context(
    context_builder_class: type | None = None,
    context_section: Any = None,
    *,
    current_turn_id: Callable[[], Any] | None = None,
) -> NativeTurnContextInstallation:
    """Install context binding lazily; injectable native seams support tests.

    Calling without arguments imports the pinned native ContextBuilder,
    ContextSection and current turn accessor. The wrapper covers already
    created and future builders because registration occurs at every build,
    once per registry. Registry registration is synchronous and guarded, with
    no global collection of registry instances.
    """

    if (
        context_builder_class is None
        or context_section is None
        or current_turn_id is None
    ):
        loaded_class, loaded_section, loaded_turn_id = _load_native_api()
        context_builder_class = context_builder_class or loaded_class
        context_section = (
            loaded_section if context_section is None else context_section
        )
        current_turn_id = current_turn_id or loaded_turn_id

    if not isinstance(context_builder_class, type):
        raise TypeError("native turn context requires a ContextBuilder class")
    if not callable(current_turn_id):
        raise TypeError("current_turn_id must be callable")

    existing_installation = vars(context_builder_class).get(_INSTALL_ATTR)
    if existing_installation is not None:
        if (
            isinstance(existing_installation, NativeTurnContextInstallation)
            and existing_installation.context_section is context_section
            and existing_installation.current_turn_id is current_turn_id
        ):
            return existing_installation
        raise RuntimeError("native turn context is already differently installed")

    original_build = getattr(context_builder_class, "build", None)
    if not callable(original_build):
        raise TypeError("native ContextBuilder does not expose build")

    async def provider(
        *, payload: Any = None, **_native_context: Any
    ) -> str:
        if not isinstance(payload, dict):
            return ""
        payload_turn_id = _valid_turn_id(payload.get("_companion_turn_id"))
        active_turn_id = _valid_turn_id(current_turn_id())
        if not payload_turn_id or payload_turn_id != active_turn_id:
            return ""
        return f"{_BINDING_TEXT}\nturn_id: {payload_turn_id}"

    def ensure_registered(registry: Any) -> None:
        providers = getattr(registry, "_providers", None)
        if not isinstance(providers, dict):
            raise TypeError("native ContextRegistry provider table is unavailable")

        with _REGISTRATION_LOCK:
            registered = providers.get(_PROVIDER_NAME)
            if registered is not None:
                if (
                    isinstance(registered, dict)
                    and registered.get("func") is provider
                    and registered.get("section") is context_section
                ):
                    return
                raise RuntimeError(
                    f"native context provider name collision: {_PROVIDER_NAME}"
                )

            registry.register_provider(
                _PROVIDER_NAME, provider, section=context_section
            )
            registered = providers.get(_PROVIDER_NAME)
            if not (
                isinstance(registered, dict)
                and registered.get("func") is provider
                and registered.get("section") is context_section
            ):
                raise RuntimeError("native context provider registration failed")

    async def wrapped_build(builder: Any, *args: Any, **kwargs: Any) -> Any:
        ensure_registered(builder.registry)
        return await original_build(builder, *args, **kwargs)

    installation = NativeTurnContextInstallation(
        context_builder_class=context_builder_class,
        context_section=context_section,
        current_turn_id=current_turn_id,
        original_build=original_build,
        wrapped_build=wrapped_build,
    )
    setattr(context_builder_class, "build", wrapped_build)
    setattr(context_builder_class, _INSTALL_ATTR, installation)
    return installation
