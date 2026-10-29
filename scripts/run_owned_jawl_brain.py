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


def write_startup_receipt(snapshot, delivery, json_format=None, goal_repair=None, action_repair=None, goal_backoff=None, terminal_context=None):
    """Persist bounded process/hook identity; no env values, prompts or thoughts."""
    import psutil

    check = {
        "delivery_guard": all(
            vars(cls).get("__jawl_native_delivery_guard_installation__") is delivery
            for cls in (delivery.react_loop_class, delivery.terminal_client_class, delivery.event_bus_class)
        ),
    }
    if terminal_context is not None:
        check["terminal_context_compaction"] = (
            vars(terminal_context.client_class).get(
                "__jawl_terminal_context_compaction_installation__"
            ) is terminal_context
            and terminal_context.client_class.get_context_block
            is terminal_context.wrapped_get_context_block
        )
    if not all(check.values()):
        raise RuntimeError("owned brain hooks were not installed on the actual native classes")
    if json_format is not None and (
        vars(json_format.provider_class).get("__jawl_owned_json_format_installation__") is not json_format
        or json_format.provider_class._request_kwargs is not json_format.wrapped_kwargs
    ):
        raise RuntimeError("owned JSON format hook was not installed on the actual provider")
    if goal_repair is not None:
        parse_chain_valid = (
            goal_repair.loop_class._parse_response is goal_repair.wrapped_parse
        )
        if not parse_chain_valid and action_repair is not None:
            # The action repair hook wraps the Goal repair parser: its saved
            # original must still be the Goal repair wrapper, so the Goal
            # completion path remains reachable in the chain.
            parse_chain_valid = (
                action_repair.original_parse is goal_repair.wrapped_parse
                and goal_repair.loop_class._handle_protocol_error is goal_repair.wrapped_error
            )
        if not (
            parse_chain_valid
            or (
                goal_repair.loop_class._handle_protocol_error is goal_repair.wrapped_error
                and vars(goal_repair.loop_class).get("__jawl_owned_goal_completion_repair__") is goal_repair
                and goal_repair.loop_class._parse_response is goal_repair.wrapped_parse
            )
        ):
            raise RuntimeError("native Goal completion repair hook is not installed")
    if action_repair is not None and (
        action_repair.loop_class._parse_response is not action_repair.wrapped_parse
        or vars(action_repair.loop_class).get("__jawl_owned_action_repair_installation__") is not action_repair
    ):
        raise RuntimeError("native action repair hook is not installed")
    if goal_backoff is not None:
        check["goal_wakeup_backoff"] = (
            goal_backoff.manager_class.should_run_heartbeat is goal_backoff.wrapped_should_run
            and goal_backoff.manager_class.seconds_until_wakeup is goal_backoff.wrapped_seconds_until
            and goal_backoff.manager_class.mark_event_pending is goal_backoff.wrapped_mark_event
            and goal_backoff.manager_class.finish_cycle is goal_backoff.wrapped_finish_cycle
            and vars(goal_backoff.manager_class).get("__jawl_owned_goal_wakeup_backoff__") is goal_backoff
        )
        if not check["goal_wakeup_backoff"]:
            raise RuntimeError("owned Goal wakeup backoff hook is not installed")
    # Recheck immediately before writing: receipt destinations are owned paths.
    check_isolation(require_clean_import=False)
    # Kernel imports stay after hook validation: importing the kernel touches
    # JAWL_LOG_DIR through its logger, which must not mask a missing hook.
    from src.l3_agent.context import companion as companion_context
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
        "action_repair_installed": action_repair is not None,
        "terminal_context_compaction": {
            "installed": terminal_context is not None,
            "keep_recent_messages": 12,
            "compact_when_source_chars_exceed": getattr(terminal_context, "target_chars", 18000),
            "target_chars": getattr(terminal_context, "target_chars", 18000),
        },
        "context_capacity": {
            "dynamic_chars": companion_context.declared_capacity_chars(),
            "goal_fixed_compaction_disabled": bool(companion_context.declared_capacity_chars()),
        },
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
    goal_repair_extension = load_extension("_owned_jawl_goal_completion_repair", "native_goal_completion_repair.py")
    goal_repair = goal_repair_extension.install_native_goal_completion_repair()

    goal_backoff_extension = load_extension("_owned_jawl_goal_wakeup_backoff", "native_goal_wakeup_backoff.py")
    goal_backoff = goal_backoff_extension.install_native_goal_wakeup_backoff()

    terminal_context_extension = load_extension(
        "_owned_terminal_context_compaction", "native_terminal_context_compaction.py"
    )
    terminal_context = terminal_context_extension.install_native_terminal_context_compaction()
    goal_repair_extension = load_extension("_owned_jawl_goal_completion_repair", "native_goal_completion_repair.py")
    goal_repair = goal_repair_extension.install_native_goal_completion_repair()
    action_repair_extension = load_extension("_owned_jawl_action_repair", "native_jawl_action_repair.py")
    action_repair = action_repair_extension.install_native_action_repair()
    json_format_extension = load_extension("_owned_jawl_json_format", "native_jawl_json_format.py")
    json_format = json_format_extension.install_native_json_format()
    write_startup_receipt(
        snapshot,
        delivery,
        json_format,
        goal_repair=goal_repair,
        action_repair=action_repair,
        goal_backoff=goal_backoff,
        terminal_context=terminal_context,
    )

    print("Owned brain entrypoint initialized.", flush=True)

    if os.environ.get("JAWL_BRAIN_BOOTSTRAP_ONLY") == "1":
        print("Owned brain bootstrap probe complete.", flush=True)
        return

    from src import main as jawl_main
    sys.exit(asyncio.run(jawl_main.main()))

if __name__ == "__main__":
    main()
