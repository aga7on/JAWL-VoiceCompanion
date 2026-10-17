"""Start the verified native brain in an isolated owned profile."""
import sys
import os
import asyncio
import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (ROOT / "runtime/jawl-sources").resolve()


def resolve_source():
    raw = os.environ.get("JAWL_SOURCE_ROOT")
    source = Path(raw).resolve() if raw else (SOURCE_ROOT / "jawl-20260906-daily-v2").resolve()
    if source == SOURCE_ROOT or not source.is_relative_to(SOURCE_ROOT) or not source.is_dir():
        raise ValueError("JAWL_SOURCE_ROOT must name a source snapshot under runtime/jawl-sources")
    return source

def load_extension(name, filename):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, ROOT / "src/jawl_voicecompanion" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def check_isolation(*, require_clean_import=True):
    if require_clean_import and "src" in sys.modules:
        raise RuntimeError("Cannot start owned scope: standard jawl 'src' is already imported. Ensure this script is the exact un-proxied entrypoint, not a submodule.")
    instances = (ROOT / "runtime/instances").resolve()
    raw_home = os.environ.get("JAWL_INSTANCE_HOME", "")
    if not raw_home or not Path(raw_home).is_absolute():
        raise ValueError("owned instance home is required")
    home = Path(raw_home).resolve()
    if home == instances or not home.is_relative_to(instances):
        raise ValueError("instance home must stay in owned runtime/instances")
    registry = os.environ.get("JAWL_INSTANCES_ROOT", "")
    if not registry or not Path(registry).is_absolute() or Path(registry).resolve() != instances:
        raise ValueError("owned JAWL_INSTANCES_ROOT is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", os.environ.get("JAWL_INSTANCE_ID", "")):
        raise ValueError("valid owned instance id is required")
    for key in ("JAWL_DATA_DIR", "JAWL_CONFIG_DIR", "JAWL_LOG_DIR", "JAWL_CACHE_DIR",
                "JAWL_PROMPT_DIR", "JAWL_SANDBOX_DIR", "JAWL_ENV_FILE"):
        raw = os.environ.get(key, "")
        if not raw or not Path(raw).is_absolute() or not Path(raw).resolve().is_relative_to(home):
            raise ValueError(f"isolated {key} is required")


def write_startup_receipt(snapshot, delivery, context, json_format=None, policy=None, goal_repair=None):
    """Persist bounded process/hook identity; no env values, prompts or thoughts."""
    import psutil

    check = {
        "delivery_guard": all(
            vars(cls).get("__jawl_native_delivery_guard_installation__") is delivery
            for cls in (delivery.react_loop_class, delivery.terminal_client_class, delivery.event_bus_class)
        ),
        "turn_context": (
            vars(context.context_builder_class).get("__jawl_native_turn_context_installation__") is context
            and context.context_builder_class.build is context.wrapped_build
        ),
    }
    if not all(check.values()):
        raise RuntimeError("owned brain hooks were not installed on the actual native classes")
    if policy is not None:
        check["policy_completion"] = (
            policy.host_class._check_security_policies is policy.wrapped_check
            and policy.registry.call_skill is policy.wrapped_call
            and vars(policy.host_class).get("__jawl_owned_policy_completion__") is policy
        )
        if not check["policy_completion"]:
            raise RuntimeError("owned policy completion hook is not installed")
    if json_format is not None and (
        vars(json_format.provider_class).get("__jawl_owned_json_format_installation__") is not json_format
        or json_format.provider_class._request_kwargs is not json_format.wrapped_kwargs
    ):
        raise RuntimeError("owned JSON format hook was not installed on the actual provider")
    if goal_repair is not None and (
        goal_repair.loop_class._parse_response is not goal_repair.wrapped_parse
        or goal_repair.loop_class._handle_protocol_error is not goal_repair.wrapped_error
        or vars(goal_repair.loop_class).get("__jawl_owned_goal_completion_repair__") is not goal_repair
    ):
        raise RuntimeError("native Goal completion repair hook is not installed")
    # Recheck immediately before writing: receipt destinations are owned paths.
    check_isolation(require_clean_import=False)
    log_dir = Path(os.environ["JAWL_LOG_DIR"]).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": 1,
        "pid": os.getpid(), "parent_pid": os.getppid(),
        "process_created_at": psutil.Process().create_time(),
        "instance_id": os.environ["JAWL_INSTANCE_ID"],
        "instance_home": str(Path(os.environ["JAWL_INSTANCE_HOME"]).resolve()),
        "source": snapshot["source"], "snapshot_sha256": snapshot["snapshot_sha256"],
        "entrypoint": str(Path(__file__).resolve()), "hooks": check,
        "local_json_format_installed": json_format is not None,
        "goal_protocol_repair_installed": goal_repair is not None,
        "bootstrap_only": os.environ.get("JAWL_BRAIN_BOOTSTRAP_ONLY") == "1",
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=log_dir,
                                         prefix=".owned-brain-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(receipt, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, log_dir / "owned-brain-startup.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return receipt

def main():
    check_isolation()
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.chdir(str(ROOT))
    source = resolve_source()
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from verify_jawl_snapshot import verify
    snapshot = verify(source)
    sys.path.insert(0, str(source))
    delivery_extension = load_extension("_owned_jawl_delivery", "native_jawl_delivery.py")
    delivery = delivery_extension.install_native_delivery_guard()
    policy_extension = load_extension("_owned_jawl_policy_completion", "native_policy_completion.py")
    policy = policy_extension.install_native_policy_completion(delivery_extension)
    goal_repair_extension = load_extension("_owned_jawl_goal_completion_repair", "native_goal_completion_repair.py")
    goal_repair = goal_repair_extension.install_native_goal_completion_repair()

    turn_context_extension = load_extension("_owned_jawl_turn_context", "native_jawl_turn_context.py")
    context = turn_context_extension.install_native_jawl_turn_context()
    json_format_extension = load_extension("_owned_jawl_json_format", "native_jawl_json_format.py")
    json_format = json_format_extension.install_native_json_format()
    write_startup_receipt(snapshot, delivery, context, json_format, policy, goal_repair=goal_repair)

    print("Owned brain entrypoint initialized.", flush=True)

    if os.environ.get("JAWL_BRAIN_BOOTSTRAP_ONLY") == "1":
        print("Owned brain bootstrap probe complete.", flush=True)
        return

    from src import main as jawl_main
    sys.exit(asyncio.run(jawl_main.main()))

if __name__ == "__main__":
    main()
