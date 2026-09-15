"""Register an already-prepared named JAWL profile for native supervision.

The script only mutates the native JAWL instance registry.  It does not start
an agent; the pinned ``src.instances.supervisor`` remains the lifecycle owner.
Use it from the disposable integrated launcher after profile preparation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1] / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--display-name", default="JAWL supervised profile")
    parser.add_argument("--source", type=Path, default=_source_root())
    parser.add_argument("--instances-root", type=Path, required=True)
    parser.add_argument("--sandbox-root", type=Path, required=True)
    parser.add_argument("--python", dest="python_executable", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    instances_root = args.instances_root.resolve()
    sandbox_root = args.sandbox_root.resolve()
    profile_home = (instances_root / args.profile).resolve()
    if instances_root not in profile_home.parents:
        parser.error("profile must remain inside instances root")
    if source == Path(source.anchor):
        parser.error("source cannot be a filesystem root")

    os.environ["JAWL_INSTANCES_ROOT"] = str(instances_root)
    os.environ["JAWL_SANDBOX_DIR"] = str(sandbox_root)
    os.environ["JAWL_INSTANCE_ID"] = args.profile
    os.environ["JAWL_INSTANCE_HOME"] = str(profile_home)
    os.environ.setdefault("JAWL_LOG_DIR", str(profile_home / "logs"))
    os.environ.setdefault("JAWL_DATA_DIR", str(profile_home / "data"))
    os.environ.setdefault("JAWL_CONFIG_DIR", str(profile_home / "config"))

    sys.path.insert(0, str(source))
    from src.instances.manager import InstanceManager  # noqa: E402

    manager = InstanceManager(
        source,
        python_executable=args.python_executable.resolve(strict=True),
        entrypoint=source / "src" / "main.py",
        instances_root=instances_root,
        shared_sandbox=sandbox_root,
    )
    try:
        existing = manager.registry.get_profile(args.profile)
    except KeyError:
        existing = None

    if existing is not None:
        current = manager.status(args.profile)
        if current["runtime"].get("alive"):
            raise RuntimeError(f"profile is already running: {args.profile}")
        profile = manager.registry.update_profile(
            args.profile,
            display_name=args.display_name,
            desired_state="stopped",
            enabled=True,
            auto_restart=True,
            restart_limit=3,
            restart_window_sec=300,
            visible_console=False,
            telegram_mode="disabled",
        )
    else:
        profile = manager.create_profile(
            args.profile,
            args.display_name,
            desired_state="stopped",
            enabled=True,
            auto_restart=True,
            restart_limit=3,
            restart_window_sec=300,
            visible_console=False,
            telegram_mode="disabled",
        )

    print(json.dumps({"ok": True, "profile": profile.public(), "registry": str(manager.registry.path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
