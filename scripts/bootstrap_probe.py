"""Bootstrap probe: run the owned brain entrypoint in bootstrap mode."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
run_root = ROOT / "runtime/instances/bootstrap-probe"
run_root.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
home = run_root
for key in ("DATA", "CONFIG", "LOG", "CACHE", "PROMPT", "SANDBOX"):
    directory = home / key.lower()
    directory.mkdir(exist_ok=True)
    env["JAWL_" + key + "_DIR"] = str(directory)
env.update(
    JAWL_INSTANCE_HOME=str(home),
    JAWL_INSTANCE_ID="bootstrap-probe",
    JAWL_INSTANCES_ROOT=str(ROOT / "runtime/instances"),
    JAWL_ENV_FILE=str(home / "env"),
    JAWL_BRAIN_BOOTSTRAP_ONLY="1",
    PYTHONPATH=str(ROOT / "runtime/jawl-sources/jawl-20260906-daily-v2"),
    PYTHONDONTWRITEBYTECODE="1",
)
(home / "env").write_text("", encoding="utf-8")
process = subprocess.run(
    [sys.executable, "-B", str(ROOT / "scripts/run_owned_jawl_brain.py")],
    cwd=str(home), env=env, capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=180,
)
print("exit code:", process.returncode)
print("STDOUT:", process.stdout[-2000:])
print("STDERR:", process.stderr[-3000:])
