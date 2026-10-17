"""Real-model ordinary/supervised turn series in exact owned Windows Jobs.

No microphone/screen capture. No foreign service reuse, credentials, local
executor or private-thought export. Test profiles are retained for diagnostics
but their native registry desired state must be stopped after cleanup.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.runtime_manifest import load_runtime_manifest
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec
from jawl_voicecompanion.worker_readiness import model_ready
from run_native_gateway_profile import NativeGatewayProfile, _parser as gateway_parser
from verify_jawl_snapshot import verify
from jawl_voicecompanion.native_jawl_json_format import install_native_json_format

INSTANCES = ROOT / "runtime/instances"
PROMPTS = (
    "Привет! Ответь одной короткой фразой.", "Как настроение? Ответь кратко.",
    "Что хорошего в спокойном вечере? Одно предложение.", "Я немного устал. Скажи пару спокойных слов.",
    "Давай просто поболтаем. С чего начнём?", "Как бы ты описала уют одним предложением?",
    "Что приятнее: дождь за окном или солнце? Коротко объясни свой выбор.",
    "Какой вымышленный мир тебе было бы интересно посетить? Одна фраза.",
    "Посоветуй короткую паузу для отдыха без запуска программ.",
    "Скажи что-нибудь забавное, но совсем короткое.",
    "Какой цвет ассоциируется у тебя со спокойствием?", "Расскажи одной фразой про любимое время суток.",
    "Придумай короткое название для уютного космического корабля.",
    "Мне нравится тихая музыка вечером. Что скажешь одной фразой?",
    "Как звучало бы приветствие робота-друга?", "Что можно представить, чтобы немного расслабиться?",
    "Задай мне один простой вопрос для беседы.", "Сегодня обычный день. Найди в этом что-нибудь хорошее.",
    "Скажи короткое пожелание хорошего вечера.", "Спасибо за разговор. Ответь коротко по-русски.",
)


def json_request(base, path, token="", body=None, timeout=3):
    headers = {"X-Console-Token": token} if token else {}
    data = None if body is None else json.dumps(body).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base + path, data=data, headers=headers)
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("acceptance response exceeds bound")
        result = json.loads(raw.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("acceptance response is not an object")
    return result


def free_ports(count):
    sockets = []
    try:
        for _ in range(count):
            item = socket.socket()
            item.bind(("127.0.0.1", 0))
            sockets.append(item)
        return [item.getsockname()[1] for item in sockets]
    finally:
        for item in sockets:
            item.close()


def listening(port):
    with socket.socket() as item:
        item.settimeout(.2)
        return item.connect_ex(("127.0.0.1", port)) == 0


def logged_command(log, command):
    # The wrapper and every descendant are born inside the supervisor's Job.
    wrapper = (
        "import subprocess,sys; "
        "f=open(sys.argv[1],'ab'); "
        "p=subprocess.run(sys.argv[2:],stdout=f,stderr=subprocess.STDOUT); "
        "f.close();sys.exit(p.returncode)"
    )
    return [sys.executable, "-B", "-c", wrapper, str(log), *command]


def validate_brain_receipt(receipt, profile, snapshot, owner):
    import psutil
    if (receipt.get("schema_version") != 1 or receipt.get("instance_id") != profile
            or receipt.get("bootstrap_only") is not False
            or receipt.get("local_json_format_installed") is not True
            or receipt.get("goal_protocol_repair_installed") is not True
            or receipt.get("hooks") != {"delivery_guard": True, "turn_context": True, "policy_completion": True}
            or Path(receipt.get("instance_home", "")).resolve() != (INSTANCES / profile).resolve()
            or Path(receipt.get("entrypoint", "")).resolve() != ROOT / "scripts/run_owned_jawl_brain.py"
            or receipt.get("snapshot_sha256") != snapshot["snapshot_sha256"]
            or Path(receipt.get("source", "")).resolve() != Path(snapshot["source"]).resolve()):
        raise ValueError("brain startup receipt does not match owned runtime")
    pid = receipt.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or not owner.owns_pid(pid):
        raise ValueError("brain PID is not in the exact launcher Job")
    if abs(psutil.Process(pid).create_time() - receipt["process_created_at"]) > .001:
        raise ValueError("brain PID creation identity changed")


def gateway(base, token, turns, prompts_file=None, *, probes=True, failure=False):
    args = gateway_parser().parse_args([
        "--url", base, "--turns", str(turns), "--timeout", "30", "--turn-timeout", "120",
        "--prompt-template", "Ответь одной короткой фразой по-русски: связь работает.",
        *(["--prompts-file", str(prompts_file)] if prompts_file else []),
        *([] if probes else ["--skip-cancel", "--skip-reconnect"]),
        *(["--allow-missing-tool-lifecycle"] if failure else []),
    ])
    args.token = token
    return NativeGatewayProfile(args).run()


def supervisor_preflight():
    # Never reconcile another owner's running/desiring-to-run profile.
    for name in ("supervisor.pid", "supervisor.lock", "supervisor.stop", "owned-supervisor-identity.json"):
        if (INSTANCES / name).exists():
            raise RuntimeError("existing native supervisor marker prevents isolated acceptance")
    registry = INSTANCES / "registry.json"
    if registry.is_file():
        state = json.loads(registry.read_text(encoding="utf-8"))
        if any(item.get("desired_state") == "running" for item in state.get("profiles", {}).values()):
            raise RuntimeError("another profile desires running; refusing global native reconciliation")


def cleanup_supervisor_lock(pid, identity=None):
    """After exact Job drain, remove only this dead supervisor's lock marker.

    Native SystemInstanceLock.release closes the lock but retains its file.
    Another process or a changed PID marker must never be cleaned by this run.
    """
    import psutil
    if psutil.pid_exists(pid):
        raise RuntimeError("supervisor PID is still live; retaining markers")
    pid_file = INSTANCES / "supervisor.pid"
    lock = INSTANCES / "supervisor.lock"
    if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() != str(pid):
        raise RuntimeError("foreign supervisor PID marker; retaining markers")
    receipt = INSTANCES / "owned-supervisor-identity.json"
    if receipt.exists():
        value = json.loads(receipt.read_text(encoding="utf-8"))
        if identity is None or value != identity or value.get("pid") != pid:
            raise RuntimeError("foreign supervisor identity receipt; retaining markers")
    if lock.exists():
        if lock.read_text(encoding="utf-8").strip() != str(pid):
            raise RuntimeError("foreign supervisor lock marker; retaining markers")
        lock.unlink()
    if pid_file.exists():
        pid_file.unlink()
    if receipt.exists():
        receipt.unlink()


def wire_probe(brain_url, model, source):
    """Use the real pinned schema without importing protected native code."""
    tree = ast.parse((Path(source) / "src/l3_agent/skills/schema.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "ACTION_SCHEMA" for target in node.targets))
    tools = ast.literal_eval(node.value)

    class ProbeProvider:
        def _request_kwargs(self, request):
            return {"model": model, "tools": tools, "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": 'Return exactly {"actions":[]} with no other keys.'}],
                    "max_tokens": 128, "temperature": 0, "stream": False}

    from types import SimpleNamespace
    install_native_json_format(ProbeProvider)
    provider = ProbeProvider()
    provider.client = SimpleNamespace(api_url=brain_url)
    kwargs = provider._request_kwargs(SimpleNamespace(tool_transport="json_envelope"))
    reply = json_request(brain_url, "/chat/completions", body=kwargs, timeout=30)
    content = reply["choices"][0]["message"]["content"]
    value = json.loads(content)
    if not isinstance(value, dict):
        raise RuntimeError("wire probe did not produce a JSON object")
    return {"passed": True, "response_is_object": True, "duplicate_sdk_wrapper": "tools" in kwargs,
            "native_schema_preserved": all(key in tools[0]["function"]["parameters"]["properties"]
                                           for key in ("v", "state", "calls", "ledger")),
            "wire_schema": kwargs["response_format"]["json_schema"]["schema"]}


def run_mode(mode, run_root, env, snapshot, model, brain, *, suite="chat", soak_seconds=28800, voice_turns=20,
             soak_interval_seconds=300):
    profile = "turn-series-" + mode + "-" + uuid4().hex[:10]
    ports = free_ports(3)
    console, control, presentation = ports
    token = uuid4().hex
    base = f"http://127.0.0.1:{console}"
    control_base = f"http://127.0.0.1:{control}"
    if mode == "supervised":
        supervisor_preflight()
    result = {"mode": mode, "profile": profile, "ports": ports, "pass": False,
              "scope": "real native model and HTTP/SSE; no audio/device acceptance", "failure": None}
    environment = dict(env, CONSOLE_TOKEN=token)
    if suite == "agent-work":
        environment["JAWL_ACCEPTANCE_CONTEXT_DIAGNOSTICS"] = "1"
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "scripts/run_integrated_profile.ps1"), "-ProfileName", profile,
               "-JawlConsolePort", str(console), "-ControlPort", str(control),
               "-PresentationPort", str(presentation), "-NoBrowser", "-NoLive2D",
               "-RunSeconds", "0", "-JawlModelOverride", model, "-StartupTimeoutSeconds", "180",
               "-JawlTemperatureOverride", "0.3", "-JawlChatTimeoutSeconds", "120",
               "-NativeContextWindowTokens", env.get("JAWL_ACCEPTANCE_CONTEXT_WINDOW_TOKENS", "0"),
               "-JawlSourceRoot", snapshot["source"]]
    if mode == "supervised":
        command.append("-EnableSupervisor")
    if suite == "agent-work":
        command.append("-EnableNativeBrowser")
    if suite == "soak":
        command.extend(["-NativeAccessLevel", "3"])
    if suite == "voice":
        command.extend(["-StartLocalAudio", "-UseVoiceMem", "-EnableStreamingAsr", "-AllowBusyStartup"])

    def ready():
        try:
            return json_request(control_base, "/api/health").get("status") in {"ok", "degraded"}
        except Exception:
            return False

    owner = RuntimeSupervisor([WorkerSpec(
        name="launcher", command=logged_command(run_root / f"{mode}-launcher.log", command),
        env=environment, cwd=str(ROOT), probe=ready, startup_timeout_seconds=240,
        max_restarts=0, stop_timeout_seconds=15,
    )])
    supervisor_pid = None
    supervisor_identity = None
    console_owned = False
    try:
        started = owner.start()
        if not started.ok:
            raise RuntimeError("integrated launcher failed readiness; inspect owned launcher log")
        admission = json_request(base, "/api/companion/admission-capabilities", token)
        console_owned = owner.owns_pid(admission["process_id"])
        if not console_owned:
            raise RuntimeError("console listener is not in the exact launcher Job")
        receipt = json.loads((INSTANCES / profile / "logs/owned-brain-startup.json").read_text(encoding="utf-8"))
        validate_brain_receipt(receipt, profile, snapshot, owner)
        result.update(brain_receipt=receipt, exact_job_proof=True, console_pid=admission["process_id"])
        if mode == "supervised":
            supervisor_pid = int((INSTANCES / "supervisor.pid").read_text())
            if not owner.owns_pid(supervisor_pid):
                raise RuntimeError("native supervisor is not owned by this launcher")
            import psutil
            supervisor_identity = json.loads((INSTANCES / "owned-supervisor-identity.json").read_text(encoding="utf-8"))
            if (supervisor_identity.get("pid") != supervisor_pid
                    or abs(supervisor_identity["process_created_at"] - psutil.Process(supervisor_pid).create_time()) > .001):
                raise RuntimeError("supervisor startup receipt creation identity differs")
            result["supervisor_identity"] = supervisor_identity
        print(json.dumps({"phase": "ready", "mode": mode, "profile": profile}), flush=True)
        if suite == "voice":
            result["voice"] = run_voice_acceptance(control_base, run_root, environment, voice_turns)
            if not result["voice"]["pass"]:
                raise RuntimeError("owned real-model browser voice acceptance failed")
        elif suite == "soak":
            from run_owned_native_soak import run_soak
            result["soak"] = run_soak(base, control_base, token, profile, snapshot["source"],
                run_root, (owner, brain), brain, duration_seconds=soak_seconds, interval_seconds=soak_interval_seconds)
            if not result["soak"]["pass"]:
                raise RuntimeError("owned native soak failed")
        elif suite == "policy":
            from run_owned_agent_work_acceptance import run_policy_refusal
            result["policy_refusal"] = run_policy_refusal(base, control_base, token, profile, run_root)
            if not result["policy_refusal"]["pass"]:
                raise RuntimeError("native policy refusal acceptance failed")
        elif suite == "agent-work":
            from run_owned_agent_work_acceptance import run_agent_work
            result["agent_work"] = run_agent_work(
                base, control_base, token, profile, run_root,
                lambda updated: validate_brain_receipt(updated, profile, snapshot, owner),
            )
            if not result["agent_work"]["pass"]:
                raise RuntimeError("native agent work/memory suite failed")
        else:
            result["turn_series"] = gateway(base, token, len(PROMPTS), run_root / "prompts.json")
            if not result["turn_series"]["pass"]:
                raise RuntimeError("correlated turn series failed")
            print(json.dumps({"phase": "twenty_turns_passed", "mode": mode}), flush=True)
        if mode == "ordinary" and suite == "chat":
            # A controlled provider loss must produce one explicit terminal error.
            brain.stop()
            result["provider_failure"] = gateway(base, token, 1, probes=False, failure=True)
            fault = result["provider_failure"]
            result["provider_failure_verified"] = bool(
                fault["scoped_event_counts"].get("turn.error") == 1
                and not fault["scoped_event_counts"].get("assistant.final") and fault["completed_turns"] == 0
            )
            if not result["provider_failure_verified"]:
                raise RuntimeError("provider loss did not produce exactly one terminal error")
            if not brain.start().ok:
                raise RuntimeError("owned provider did not recover")
            result["provider_recovery"] = gateway(base, token, 1, probes=False)
            if not result["provider_recovery"]["pass"]:
                raise RuntimeError("normal turn after provider restart failed")
        result["pass"] = True
    except Exception as exc:
        result["failure"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        if console_owned:
            try:
                json_request(base, "/api/agent/stop", token, {}, timeout=20)
            except Exception:
                result["graceful_agent_stop_ack"] = False
            else:
                result["graceful_agent_stop_ack"] = True
        if supervisor_pid is not None and owner.owns_pid(supervisor_pid):
            (INSTANCES / "supervisor.stop").write_text("stop\n", encoding="utf-8")
            deadline = time.monotonic() + 5
            while (INSTANCES / "supervisor.pid").exists() and time.monotonic() < deadline:
                time.sleep(.1)
        try:
            owner.stop()
            if supervisor_pid is not None:
                cleanup_supervisor_lock(supervisor_pid, supervisor_identity)
        except Exception as exc:
            result["cleanup_error"] = type(exc).__name__
            result["pass"] = False
        result["ports_clear"] = not any(listening(port) for port in ports)
        result["profile_retained_for_diagnostics"] = str(INSTANCES / profile)
        if mode == "supervised":
            registry_path = INSTANCES / "registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
            result["desired_state_stopped"] = registry.get("profiles", {}).get(profile, {}).get("desired_state") == "stopped"
            result["supervisor_markers_clear"] = not any((INSTANCES / name).exists() for name in ("supervisor.pid", "supervisor.lock", "supervisor.stop", "owned-supervisor-identity.json"))
            result["pass"] = result["pass"] and result["desired_state_stopped"] and result["supervisor_markers_clear"]
        result["pass"] = result["pass"] and result["ports_clear"]
    return result


def run_voice_acceptance(control_base, run_root, environment, turns):
    """Three WAV fixtures repeated through real /app; browser has its own Job."""
    report_path = Path(run_root) / "browser-voice.json"
    evidence = Path(run_root) / "browser-voice-evidence"
    command = [sys.executable, "-X", "utf8", "-B",
               str(ROOT / "scripts/run_browser_voice_e2e.py"), "--live", "--ui", "app",
               "--require-draft-preview", "--url", control_base,
               "--report", str(report_path), "--evidence-dir", str(evidence)]
    for index in range(turns):
        fixture = index % 3
        command.extend(["--wav", str(ROOT / f"runtime/synthetic-questions/question-0{fixture + 1}.wav"),
                        "--expected=" + ("статус", "короткие", "тестовый")[fixture]])
    owner = RuntimeSupervisor([WorkerSpec(name="voice-browser", command=logged_command(Path(run_root) / "voice-browser.log", command),
        probe=None, cwd=str(ROOT), env=environment, max_restarts=0, stop_timeout_seconds=15)])
    result = {"pass": False, "requested_turns": turns, "fixture_count": 3,
              "scope": "synthetic WAV, real GigaAM/Hikari/OmniVoice and /app WebAudio; no physical mic/audibility",
              "report": str(report_path)}
    try:
        started = owner.start()
        if not started.ok:
            raise RuntimeError("owned browser harness failed startup")
        pid = started.worker_summary("voice-browser")["pid"]
        import psutil
        process = psutil.Process(pid)
        process.wait(timeout=max(900, turns * 180))
        with report_path.open("rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise RuntimeError("browser voice report exceeds bound")
        receipt = json.loads(raw)
        result["completed_turns"] = len(receipt.get("turns", []))
        result["status"] = receipt.get("status")
        result["pass"] = receipt.get("status") == "passed" and result["completed_turns"] == turns
    except Exception as exc:
        result["failure"] = type(exc).__name__ + ": " + str(exc)[:240]
    finally:
        try:
            owner.stop()
            result["browser_job_drained"] = True
        except Exception as exc:
            result["cleanup_error"] = type(exc).__name__
            result["pass"] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--mode", choices=("ordinary", "supervised", "both"), default="both")
    parser.add_argument("--suite", choices=("chat", "agent-work", "policy", "soak", "voice"), default="chat")
    parser.add_argument("--soak-seconds", type=float, default=28800)
    parser.add_argument("--soak-interval-seconds", type=float, default=300)
    parser.add_argument("--voice-turns", type=int, default=20)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live for actual owned model/agent startup")
    if sys.platform != "win32":
        parser.error("exact Windows Job ownership is required")
    if args.report.exists():
        parser.error("report already exists; preserve the previous evidence")
    if args.suite == "soak" and (args.mode == "both" or not 30 <= args.soak_seconds <= 28800):
        parser.error("soak requires one explicit mode and duration 30..28800 seconds")
    if not 3 <= args.voice_turns <= 60:
        parser.error("voice turns must be between 3 and 60")
    if not 0 <= args.soak_interval_seconds <= 3600:
        parser.error("soak interval must be between zero and3600 seconds")
    manifest = load_runtime_manifest(repo_root=ROOT)
    if manifest["brain"]["device"].casefold() != "cuda1":
        parser.error("this acceptance is scoped to the selected GPU1 brain")
    snapshot = verify(ROOT / "runtime/jawl-sources/jawl-20260906-daily-v2")
    run_root = ROOT / "runtime" / ("gateway-series-" + uuid4().hex[:12])
    run_root.mkdir()
    (run_root / "prompts.json").write_text(json.dumps(PROMPTS, ensure_ascii=False), encoding="utf-8")
    brain_port = free_ports(1)[0]
    brain_url = f"http://127.0.0.1:{brain_port}/v1"
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC",
           "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "PROGRAMFILES",
           "PROGRAMFILES(X86)", "PROGRAMW6432", "HOMEDRIVE", "HOMEPATH") if key in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", NO_PROXY="*",
               LLM_API_URL=brain_url, LLM_API_KEY_1="local-loopback", LLM_REASONING_EFFORT="none",
               LLM_MAX_OUTPUT_TOKENS=str(manifest["brain"]["max_output_tokens"]))
    env["JAWL_ACCEPTANCE_CONTEXT_WINDOW_TOKENS"] = str(manifest["brain"]["context_size"])
    model = manifest["brain"]["model"]
    command = [sys.executable, "-B", str(ROOT / "scripts/hold_supervised_brain.py"),
               "--port", str(brain_port), "--url", brain_url]
    brain = RuntimeSupervisor([WorkerSpec(
        name="brain", command=logged_command(run_root / "brain.log", command), env=env,
        cwd=str(ROOT), probe=lambda: model_ready(brain_port, model), startup_timeout_seconds=240,
        max_restarts=0, stop_timeout_seconds=15,
    )])
    report = {"schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
              "run_root": str(run_root), "model": model, "snapshot": snapshot,
              "suite": args.suite, "modes": [], "pass": False}
    try:
        if not brain.start().ok:
            raise RuntimeError("owned selected model failed readiness")
        report["wire_probe"] = wire_probe(brain_url, model, snapshot["source"])
        print(json.dumps({"phase": "wire_probe_passed"}), flush=True)
        for mode in (("ordinary", "supervised") if args.mode == "both" else (args.mode,)):
            result = run_mode(mode, run_root, env, snapshot, model, brain, suite=args.suite,
                              soak_seconds=args.soak_seconds, voice_turns=args.voice_turns,
                              soak_interval_seconds=args.soak_interval_seconds)
            report["modes"].append(result)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"phase": "mode_finished", "mode": mode, "pass": result["pass"]}), flush=True)
            if not result["pass"]:
                break
        report["pass"] = bool(report["modes"]) and all(item["pass"] for item in report["modes"])
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        try:
            brain.stop()
        except Exception as exc:
            report["brain_cleanup_error"] = type(exc).__name__
            report["pass"] = False
        report["brain_port_clear"] = not listening(brain_port)
        report["pass"] = report["pass"] and report["brain_port_clear"]
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "report": str(args.report)}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
