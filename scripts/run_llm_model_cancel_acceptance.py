"""Opt-in selected-GGUF CPU cancellation probe; never changes the daily profile.

Native pinned JAWL SDK -> owned llama-server -> real slot telemetry/follow-up.
No microphones/tools/agent loop, downloads or foreign process stop. CPU mode
never offloads; GPU1 mode is a separate explicit opt-in using canonical settings.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from jawl_voicecompanion.runtime_manifest import load_runtime_manifest
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec, _windows_job_object, _assign_to_job, _close_windows_job
from run_llm_cancel_acceptance import PINNED_PYTHON, PINNED_SOURCE, child_environment
from run_tera_cancel_acceptance import GIB, RamGuard, free_ram, listener_pids


def admit_ram(available: int, model_bytes: int) -> bool:
    return available >= model_bytes + 10 * GIB


def cpu_command(exe: Path, model: Path, alias: str, port: int, threads: int) -> list[str]:
    return [str(exe), '--model', str(model), '--alias', alias, '--host', '127.0.0.1',
            '--port', str(port), '--threads', str(threads), '--ctx-size', '4096',
            '--parallel', '1', '--device', 'none', '--gpu-layers', '0', '--fit', 'off',
            '--no-kv-offload', '--no-op-offload', '--slots', '--no-warmup',
            '--batch-size', '16', '--ubatch-size', '1']


def gpu1_command(exe: Path, model: Path, alias: str, port: int,
                 threads: int, context_size: int, gpu_layers: int,
                 device: str) -> list[str]:
    """Build the canonical single-slot GPU1 command without fit/offload fallback."""
    if device != 'CUDA1' or type(gpu_layers) is not int or gpu_layers <= 0:
        raise ValueError('GPU1 probe requires device CUDA1 and positive GPU layers')
    return [str(exe), '--model', str(model), '--alias', alias, '--host', '127.0.0.1',
            '--port', str(port), '--threads', str(threads), '--ctx-size', str(context_size),
            '--parallel', '1', '--device', device, '--gpu-layers', str(gpu_layers),
            '--fit', 'off', '--slots', '--no-warmup']


def admit_gpu1(free_bytes: int, model_bytes: int) -> bool:
    return free_bytes >= model_bytes + 2 * GIB


def probe_environment(root: Path, mode: str) -> dict[str, str]:
    env = child_environment(root)
    if mode == 'gpu1' and os.environ.get('ProgramFiles'):
        # NVML fails initialization in a minimal Windows environment without
        # this machine path. Do not inherit profile paths or credential vars.
        env['ProgramFiles'] = os.environ['ProgramFiles']
    return env


def gpu1_free_bytes() -> int:
    """Read physical GPU index 1's free-memory counter; never expose stderr."""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--id=1', '--query-gpu=memory.free',
             '--format=csv,noheader,nounits'],
            check=True, capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().splitlines()
        if len(lines) != 1 or not lines[0].strip().isdigit():
            raise ValueError('invalid memory counter')
        return int(lines[0].strip()) * 1024 ** 2
    except Exception:
        # Avoid bubbling up command output, which may contain machine details.
        raise RuntimeError('GPU1 memory admission unavailable') from None


def slot_state(payload) -> dict:
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError('expected exactly one monitored slot')
    raw = payload[0]
    active, context, task = raw.get('is_processing'), raw.get('n_ctx'), raw.get('id_task')
    if type(active) is not bool or type(context) is not int or context <= 0:
        raise ValueError('invalid slot state/context')
    if task is not None and (type(task) is not int or task < 0):
        raise ValueError('invalid slot task identity')
    tokens = raw.get('next_token')
    if tokens is None and not active:
        decoded = 0
    else:
        if not isinstance(tokens, list) or len(tokens) != 1 or not isinstance(tokens[0], dict):
            raise ValueError('invalid slot token telemetry')
        decoded = tokens[0].get('n_decoded')
        if type(decoded) is not int or decoded < 0:
            raise ValueError('invalid decoded token count')
    if active and task is None:
        raise ValueError('active slot has no task identity')
    return {'id_task': task, 'is_processing': active, 'n_decoded': decoded, 'n_ctx': context}


def _write(path, report):
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def child_probe(root: Path, report: dict, mode: str = 'cpu') -> None:
    if mode not in {'cpu', 'gpu1'}:
        raise ValueError('unsupported probe mode')
    manifest = load_runtime_manifest()
    exe, model = (Path(manifest['models'][key]) for key in ('brain_server_exe', 'bonsai_model'))
    if not exe.is_file() or not model.is_file():
        raise ValueError('selected model/server is missing')
    available = free_ram()
    brain = manifest['brain']
    context_size = 4096 if mode == 'cpu' else brain['context_size']
    device_name = 'CPU' if mode == 'cpu' else 'GPU1'
    report.update(model=str(model), model_bytes=model.stat().st_size,
                  model_mtime_ns=model.stat().st_mtime_ns, executable=str(exe),
                  executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                  available_ram_before_start=available, benchmark_device=device_name,
                  benchmark_context=context_size, canonical_device_unchanged=brain['device'])
    if not admit_ram(available, model.stat().st_size):
        report.update(status='skipped', reason='requires_model_size_plus_10GiB_available')
        return
    if mode == 'gpu1':
        try:
            gpu_available = gpu1_free_bytes()
        except RuntimeError:
            report.update(status='skipped', reason='gpu1_memory_admission_unavailable')
            return
        report['available_gpu1_bytes_before_start'] = gpu_available
        if not admit_gpu1(gpu_available, model.stat().st_size):
            report.update(status='skipped', reason='gpu1_requires_model_size_plus_2GiB_available')
            return
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    base, alias = f'http://127.0.0.1:{port}', manifest['brain']['model']
    opener = build_opener(ProxyHandler({})).open

    def read_json(route):
        with opener(base + route, timeout=1) as response:
            raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError('telemetry exceeded bounded limit')
        return json.loads(raw)

    log = root / 'server.log'
    if mode == 'cpu':
        command = cpu_command(exe, model, alias, port, brain['threads'])
    else:
        command = gpu1_command(exe, model, alias, port, brain['threads'],
                               brain['context_size'], brain['gpu_layers'], brain['device'])
    report['server_command'] = command  # own credential-free command, never process enumeration
    # The supervised wrapper retains the actual server log; Win Job membership
    # of its real listener is checked before any inference mutation.
    wrapper = ('import subprocess,sys; from pathlib import Path; f=Path(' + repr(str(log))
               + ").open('xb'); p=subprocess.run(" + repr(command)
               + ',stdout=f,stderr=subprocess.STDOUT); f.close();sys.exit(p.returncode)')
    environment = os.environ.copy()
    if mode == 'cpu':
        environment.update(CUDA_VISIBLE_DEVICES='-1', GGML_VK_VISIBLE_DEVICES='-1')
    supervisor = RuntimeSupervisor([WorkerSpec(
        'llm-model-probe', [str(PINNED_PYTHON), '-B', '-c', wrapper],
        probe=lambda: read_json('/health').get('status') == 'ok', cwd=str(root), env=environment,
        startup_timeout_seconds=60, max_restarts=0, stop_timeout_seconds=2)])
    guard = RamGuard(supervisor.stop, floor=8 * GIB, seconds=120)
    guard.thread.start()
    listener_ids, server_process = set(), None
    try:
        report['stage'] = f'{mode}_server_start'
        startup_at = time.perf_counter()
        startup = supervisor.start()
        report.update(startup_seconds=round(time.perf_counter() - startup_at, 3),
                      startup=startup.workers, port=port)
        guard.check()
        if not startup.ok:
            raise RuntimeError(f'owned {device_name} server startup failed')
        server_process = supervisor._states['llm-model-probe'].process
        listener_ids = listener_pids(port)
        report['stage'] = 'owned_listener_readback'
        report['listener_pids'] = sorted(listener_ids)
        if not listener_ids or not all(supervisor.owns_pid(pid) for pid in listener_ids):
            raise RuntimeError('exact owned Job listener proof failed')
        models = read_json('/v1/models')
        if alias not in [item.get('id') for item in models.get('data', [])]:
            raise RuntimeError('selected alias was not read back')
        initial = slot_state(read_json('/slots'))
        if initial['is_processing'] or initial['n_ctx'] != context_size:
            raise RuntimeError('owned initial slot/context mismatch')
        report['initial_slot'] = initial

        sys.path.insert(0, str(PINNED_SOURCE))
        report['stage'] = 'pinned_native_sdk_import'
        from src.l3_agent.llm.api_keys.rotator import APIKeyRotator
        from src.l3_agent.llm.client import LLMClient
        from src.l3_agent.llm.providers import LLMMessage, LLMRequest, OpenAICompatibleProvider
        import openai
        import httpx
        report.update(openai_sdk_version=openai.__version__, httpx_version=httpx.__version__)
        report['provider_source_sha256'] = hashlib.sha256(
            (PINNED_SOURCE / 'src/l3_agent/llm/providers/openai_compatible.py').read_bytes()).hexdigest()
        client = LLMClient(base + '/v1', APIKeyRotator(['jawl-loopback-acceptance-key']),
                           connect_timeout=2, read_timeout=40)
        provider = OpenAICompatibleProvider(client, request_timeout_seconds=40)

        async def exercise():
            tasks = []

            async def invoke(text):
                return await provider.complete(LLMRequest(
                    model=alias, messages=(LLMMessage(role='user', content=text),),
                    stream=True, enable_reasoning=False, temperature=0, timeout_seconds=40))

            async def wait_slot(predicate, seconds):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    guard.check()
                    raw = await asyncio.to_thread(read_json, '/slots')
                    state = slot_state(raw)
                    processed = raw[0].get('n_prompt_tokens_processed', 0)
                    state['n_prompt_tokens_processed'] = processed if type(processed) is int else 0
                    report['last_observed_slot'] = state
                    if predicate(state):
                        return state
                    await asyncio.sleep(.05)
                raise TimeoutError('required real slot transition was not observed')

            try:
                os.environ['LLM_MAX_OUTPUT_TOKENS'] = '256'
                task = asyncio.create_task(invoke('Перечисляй целые числа от одного до тысячи без пояснений.'))
                tasks.append(task)
                report['stage'] = 'observe_actual_prefill_or_generation'
                # On a slow CPU, cancellation during real prefill is a useful
                # distinct phase. Never call it mid-generation/streaming proof.
                report['required_cancel_phase'] = 'generation' if mode == 'gpu1' else 'prefill_or_generation'
                active = await wait_slot(lambda s: s['is_processing'] and
                                         (s['n_decoded'] >= 2 or
                                          (mode == 'cpu' and s['n_prompt_tokens_processed'] >= 1)), 35)
                if task.done():
                    raise AssertionError('request completed before cancellation')
                report['slot_before_cancel'] = active
                report['cancel_phase'] = 'generation' if active['n_decoded'] >= 2 else 'prefill'
                report['stage'] = 'native_cancel_and_slot_idle'
                started = time.perf_counter()
                task.cancel()
                try:
                    await asyncio.wait_for(task, 2)
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError('native SDK task did not propagate cancellation')
                report['native_cancel_return_ms'] = round((time.perf_counter() - started) * 1000, 3)
                idle = await wait_slot(lambda s: not s['is_processing'], 3)
                report.update(cancel_to_slot_idle_ms=round((time.perf_counter() - started) * 1000, 3),
                              slot_after_cancel=idle)
                await asyncio.sleep(.35)
                settled = slot_state(await asyncio.to_thread(read_json, '/slots'))
                if settled['is_processing'] or settled['n_decoded'] != idle['n_decoded']:
                    raise AssertionError('cancelled decode continued after idle')
                report['settled_slot'] = settled
                # Selected models may consume the tiny 12-token diagnostic cap
                # before user-visible text. Use the actual canonical output budget.
                os.environ['LLM_MAX_OUTPUT_TOKENS'] = str(brain['max_output_tokens'])
                report['followup_output_budget'] = brain['max_output_tokens']
                report['followups'] = []
                report['stage'] = 'same_native_client_followups'
                for text in ('Ответь кратко по-русски: ты готова?', 'Сколько будет два плюс два?'):
                    started_b = time.perf_counter()
                    result = await asyncio.wait_for(invoke(text), 35)
                    if not result.content.strip():
                        raise AssertionError('same-client real follow-up returned no text')
                    report['followups'].append({'text': result.content[:400],
                                                'seconds': round(time.perf_counter() - started_b, 3)})
                    await wait_slot(lambda s: not s['is_processing'], 3)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.wait_for(provider.close(), 3)

        asyncio.run(exercise())
        report['status'] = 'passed'
    finally:
        errors = []
        for stage, action in (('supervisor_stop', supervisor.stop), ('guard_join', guard.close)):
            try:
                action()
            except Exception as exc:
                errors.append({'stage': stage, 'error_type': type(exc).__name__})
        report.update(minimum_available_ram=guard.minimum, guard_reason=guard.reason,
                      cleanup_errors=errors,
                      observed_server_launcher_exit=server_process.poll() if server_process else None)
        if listener_ids:
            report['owned_listener_gone'] = not (listener_ids & listener_pids(port))
            if not report['owned_listener_gone']:
                errors.append({'stage': 'owned_listener_remained'})
        if errors or guard.reason or guard.stop_error:
            report.update(status='failed', reason=guard.reason or 'owned_cleanup_failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    opt_in = parser.add_mutually_exclusive_group()
    opt_in.add_argument('--allow-cpu-model', action='store_true')
    opt_in.add_argument('--allow-gpu1-model', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--child-root', type=Path)
    args = parser.parse_args()
    target = args.report.resolve()
    if (ROOT / 'runtime' not in target.parents or target.suffix != '.json'
            or target.exists() or not target.parent.is_dir()):
        parser.error('report must be a new JSON inside owned runtime')
    if (not (args.allow_cpu_model or args.allow_gpu1_model)
            or sys.platform != 'win32'):
        parser.error('explicit --allow-cpu-model or --allow-gpu1-model on Windows is required')
    mode = 'gpu1' if args.allow_gpu1_model else 'cpu'
    if args.child_root is not None:
        root = args.child_root.resolve()
        if ROOT / 'runtime/instances' not in root.parents or not root.is_dir():
            parser.error('invalid isolated child root')
        report = {'status': 'failed', 'started_at': datetime.now(timezone.utc).isoformat(),
                  'scope': ('actual selected GGUF GPU1 + pinned native SDK; no agent/voice acceptance'
                            if mode == 'gpu1' else
                            'actual selected GGUF CPU + pinned native SDK; no agent/voice/GPU1 acceptance'),
                  'benchmark_device': 'GPU1' if mode == 'gpu1' else 'CPU',
                  'run_root': str(root), 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        try:
            child_probe(root, report, mode)
        except Exception as exc:
            report.update(status='failed', error_type=type(exc).__name__)
        report['ended_at'] = datetime.now(timezone.utc).isoformat()
        _write(target, report)
        return 0 if report['status'] in {'passed', 'skipped'} else 1
    from verify_jawl_snapshot import verify
    verify(PINNED_SOURCE)
    root = ROOT / 'runtime/instances' / ('llm-model-probe-' + uuid4().hex[:12])
    root.mkdir()
    env = probe_environment(root, mode)
    env.update(JAWL_CACHE_DIR=str(root / 'cache'), JAWL_INSTANCES_ROOT=str(ROOT / 'runtime/instances'))
    job = _windows_job_object()
    if job is None:
        parser.error('owned Job unavailable')
    child = None
    code = 1
    try:
        with (root / 'probe.log').open('xb') as output:
            child = subprocess.Popen([str(PINNED_PYTHON), '-B', str(Path(__file__).resolve()),
                                      '--allow-gpu1-model' if mode == 'gpu1' else '--allow-cpu-model',
                                      '--child-root', str(root), '--report', str(target)],
                                     cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
            _assign_to_job(job, child)
            print(json.dumps({'child_pid': child.pid, 'root': str(root), 'report': str(target)}), flush=True)
            code = child.wait(timeout=150)
    finally:
        _close_windows_job(job)
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
        report = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'status': 'failed'}
        report.update(observed_child_exit=child.returncode if child else None,
                      parent_exit=code, owned_job_closed=True)
        if code != 0:
            report['status'] = 'failed'
        _write(target, report)
        print(json.dumps({'status': report['status'], 'parent_exit': code}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
