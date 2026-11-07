import os
import subprocess
import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent

# Prepare clean environment without duplicate Win32 keys
clean_env = dict(os.environ)
cuda_bin = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin"
if os.path.exists(cuda_bin) and cuda_bin not in clean_env.get("PATH", ""):
    clean_env["PATH"] = cuda_bin + ";" + clean_env.get("PATH", "")

clean_env["PYTHONIOENCODING"] = "utf-8"
clean_env["PYTHONUNBUFFERED"] = "1"

cmd = [
    "powershell.exe",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", str(repo / "scripts" / "run_local_bonsai_integrated.ps1"),
    "-ManifestPath", str(repo / "runtime" / "sensenova-loop" / "runtime.manifest.gpu.json"),
    "-ProfileName", "daily",
    "-SyncProfile",
    "-StartDesktopShell",
    "-EnableAmbientAudio",
    "-StartAmbientAudio",
    "-EnableScreenWatch",
    "-EnableScreenOcr",
    "-RunSeconds", "0",
]

print(f"Launching integrated stack with clean env from {repo}...")
proc = subprocess.Popen(
    cmd,
    cwd=str(repo),
    env=clean_env,
    stdout=sys.stdout,
    stderr=sys.stderr,
)

proc.wait()
sys.exit(proc.returncode)
