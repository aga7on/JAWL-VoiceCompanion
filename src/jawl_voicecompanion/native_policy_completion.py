"""End a correlated request after native HostOS authority denies an action.

Observe the native security check, never reimplement its policy or interpret
tool output text. Native journals still record the failed attempt. Remaining
actions in the same batch cannot run after the denial. Durable goals and
uncorrelated autonomous cycles retain native behavior.
"""
from contextvars import ContextVar
from dataclasses import dataclass
import importlib

_INSTALL = "__jawl_owned_policy_completion__"
_ATTEMPT = ContextVar("owned_native_policy_attempt", default=None)


@dataclass
class Installation:
    host_class: type
    registry: object
    wrapped_check: object
    wrapped_call: object


def install_native_policy_completion(delivery, host_class=None, registry=None):
    if host_class is None:
        host_class = importlib.import_module("src.l2_interfaces.host.os.client").HostOSClient
    if registry is None:
        registry = importlib.import_module("src.l3_agent.skills.registry")
    existing = vars(host_class).get(_INSTALL)
    if existing is not None:
        if (existing.registry is registry and registry.call_skill is existing.wrapped_call
                and host_class._check_security_policies is existing.wrapped_check):
            return existing
        raise RuntimeError("native policy completion is partially or differently installed")
    original_check = host_class._check_security_policies
    original_call = registry.call_skill

    def checked(host, *args, **kwargs):
        try:
            return original_check(host, *args, **kwargs)
        except PermissionError:
            attempt = _ATTEMPT.get()
            if attempt is not None:
                attempt[0] = True
            raise

    async def call(*args, **kwargs):
        if delivery.native_policy_denied():
            result = registry.SkillResult.fail("Request stopped after native HostOS policy denial.")
            result.terminate_loop = True
            return result
        attempt = [False]
        token = _ATTEMPT.set(attempt)
        try:
            result = await original_call(*args, **kwargs)
            if attempt[0] and delivery.record_native_policy_denial():
                result.terminate_loop = True
            return result
        finally:
            _ATTEMPT.reset(token)

    installation = Installation(host_class, registry, checked, call)
    host_class._check_security_policies = checked
    registry.call_skill = call
    setattr(host_class, _INSTALL, installation)
    return installation
