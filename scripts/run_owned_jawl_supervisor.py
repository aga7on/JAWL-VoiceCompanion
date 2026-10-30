"""Launch pinned native instance supervisor with the owned brain entrypoint."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (ROOT / "runtime/jawl-sources").resolve()


def resolve_source() -> Path:
    raw = os.environ.get("JAWL_SOURCE_ROOT")
    source = Path(raw).resolve() if raw else (SOURCE_ROOT / "jawl-20260906-daily-v2").resolve()
    if source == SOURCE_ROOT or not source.is_relative_to(SOURCE_ROOT) or not source.is_dir():
        raise ValueError("JAWL_SOURCE_ROOT must name a source snapshot under runtime/jawl-sources")
    return source


def main() -> int:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from verify_jawl_snapshot import verify
    source = resolve_source()
    verify(source)
    sys.path.insert(0, str(source))
    from src.instances.manager import InstanceManager
    from src.instances import supervisor

    owned_brain = (ROOT / "scripts" / "run_owned_jawl_brain.py").resolve(strict=True)
    original_init = InstanceManager.__init__

    def owned_init(self, project_root, **kwargs):
        kwargs.setdefault("entrypoint", owned_brain)
        return original_init(self, project_root, **kwargs)

    InstanceManager.__init__ = owned_init
    import importlib.util
    spec = importlib.util.spec_from_file_location("_owned_supervisor_identity", ROOT / "src/jawl_voicecompanion/native_supervisor_identity.py")
    extension = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = extension
    spec.loader.exec_module(extension)
    extension.install_native_supervisor_identity(InstanceManager, supervisor)
    return supervisor.main()


if __name__ == "__main__":
    raise SystemExit(main())
