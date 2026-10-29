"""Replay a fixed, privacy-safe 20-case sensory suite against local models.

The run uses only existing video/image/WAV fixtures plus in-memory audio
variants. It never opens a physical capture device and never stores raw input
or transcript text. Qwen runs in an owned CPU-only child process.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import os
import random
import shutil
import socket
import subprocess
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
QWEN_MODEL = ROOT / "runtime/vlm-cpu-bench/models/qwen3.5-0.8b/Qwen3.5-0.8B-Q4_K_M.gguf"
QWEN_MMPROJ = ROOT / "runtime/vlm-cpu-bench/models/qwen3.5-0.8b/mmproj-F16.gguf"
LLAMA_SERVER = ROOT / "runtime/gemma4-e4b-cpu/llama.cpp/llama-server.exe"
QWEN_PORT = 8994
VIDEO_DIR = ROOT / "runtime/vlm-cpu-bench/video"
AUDIO_DIR = ROOT / "runtime/synthetic-questions"
ASR_EXE = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
ASR_MODEL = ROOT / "runtime/models/asr/gigaam-v3-e2e-rnnt-q8_0.gguf"


def read_wav(path: Path) -> tuple[int, list[int]]:
    with wave.open(str(path), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        if width != 2 or channels not in (1, 2):
            raise ValueError(f"unsupported fixture format: {path.name}")
        raw = wav.readframes(wav.getnframes())
    samples = [int.from_bytes(raw[i:i + 2], "little", signed=True) for i in range(0, len(raw), 2)]
    if channels == 2:
        samples = [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples), 2)]
    return rate, samples


def wav_bytes(rate: int, samples: list[int]) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
        wav.writeframes(b"".join(max(-32768, min(32767, int(x))).to_bytes(2, "little", signed=True) for x in samples))
    return out.getvalue()


def _silent(rate: int, seconds: float) -> list[int]:
    return [0] * int(rate * seconds)


def _gain(samples: list[int], db: float) -> list[int]:
    factor = 10 ** (db / 20)
    return [int(x * factor) for x in samples]


def _noise(samples: list[int], snr_db: float, seed: int) -> list[int]:
    rng = random.Random(seed)
    rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples))) or 1.0
    sigma = rms / (10 ** (snr_db / 20))
    return [int(x + rng.gauss(0, sigma)) for x in samples]


def _noise_only(rate: int, seconds: float, seed: int) -> list[int]:
    rng = random.Random(seed)
    return [int(rng.gauss(0, 700)) for _ in range(int(rate * seconds))]


def make_cases() -> list[dict[str, Any]]:
    image = lambda name: (VIDEO_DIR / name).read_bytes()
    source: dict[str, tuple[int, list[int]]] = {
        f"speech_{i}": read_wav(AUDIO_DIR / f"question-0{i}.wav") for i in (1, 2, 3)
    }
    rate, q1 = source["speech_1"]
    _, q2 = source["speech_2"]
    _, q3 = source["speech_3"]
    silence = _silent(rate, 2.0)
    return [
        {"id":"V01-earth-frame-01", "modality":"vision", "image":image("frame-01.jpg"), "truth":["earth","planet"]},
        {"id":"V02-earth-frame-05", "modality":"vision", "image":image("frame-05.jpg"), "truth":["earth","planet"]},
        {"id":"V03-icon-card", "modality":"vision", "image":image("frame-06.jpg"), "truth":["card","icon","dark"]},
        {"id":"V04-static-card", "modality":"vision", "image":image("frame-07.jpg"), "truth":["card","icon","dark"]},
        {"id":"V05-return-to-earth", "modality":"vision", "image":image("frame-08.jpg"), "truth":["earth","planet"]},
        {"id":"V06-earth-frame-12", "modality":"vision", "image":image("frame-12.jpg"), "truth":["earth","planet"]},
        {"id":"V07-earth-to-card-pair", "modality":"vision", "image":image("pair-05-06.jpg"), "truth":["earth","card","transition"]},
        {"id":"V08-card-to-earth-pair", "modality":"vision", "image":image("pair-07-08.jpg"), "truth":["earth","card","transition"]},
        {"id":"A09-russian-speech-1", "modality":"audio", "wav":wav_bytes(*source["speech_1"]), "asr":True, "truth":["speech","russian"]},
        {"id":"A10-russian-speech-2", "modality":"audio", "wav":wav_bytes(*source["speech_2"]), "asr":True, "truth":["speech","russian"]},
        {"id":"A11-russian-speech-3", "modality":"audio", "wav":wav_bytes(*source["speech_3"]), "asr":True, "truth":["speech","russian"]},
        {"id":"A12-short-phrase-pause", "modality":"audio", "wav":wav_bytes(rate,q1+_silent(rate,.5)), "asr":True, "truth":["speech","pause"]},
        {"id":"A13-long-phrase-pause", "modality":"audio", "wav":wav_bytes(rate,q2+_silent(rate,2)), "asr":True, "truth":["speech","pause"]},
        {"id":"A14-quiet-speech", "modality":"audio", "wav":wav_bytes(rate,_gain(q1,-18)), "asr":True, "truth":["speech","quiet"]},
        {"id":"A15-speech-noise-snr10", "modality":"audio", "wav":wav_bytes(rate,_noise(q3,10,15)), "asr":True, "truth":["speech","noise"]},
        {"id":"A16-noise-only-negative", "modality":"audio", "wav":wav_bytes(rate,_noise_only(rate,2,16)), "asr":False, "truth":["noise","no-speech"]},
        {"id":"A17-silence-negative", "modality":"audio", "wav":wav_bytes(rate,silence), "asr":False, "truth":["silence","no-speech"]},
        {"id":"A18-music-context", "modality":"audio", "wav_path":ROOT/"runtime/crane-repo/data/audio/toccata-amp-fugue-js-bach.mp3", "truth":["music","instrumental"]},
        {"id":"AV19-speech-over-scene", "modality":"audio_visual", "image":image("frame-01.jpg"), "wav":wav_bytes(rate,q1), "asr":True, "truth":["earth","speech","russian"]},
        {"id":"C20-current-playback-suppression-contract", "modality":"contract", "truth":["playback-suppression","no-raw-capture"]},
    ]


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _json_request(url: str, payload: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=data, headers={"Content-Type":"application/json"} if data else {})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_audio(path: Path) -> bytes:
    if path.suffix.lower() == ".wav":
        return path.read_bytes()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to decode the local music fixture")
    proc = subprocess.run([ffmpeg,"-v","error","-i",str(path),"-f","wav","-ac","1","-ar","16000","pipe:1"],
                          capture_output=True,timeout=30)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("ffmpeg could not decode the local music fixture")
    return proc.stdout


def _cpu_percent() -> float | None:
    try:
        import psutil
        return round(float(psutil.cpu_percent(interval=0.1)), 1)
    except Exception:
        return None


def _process_rss(pid: int | None) -> int | None:
    if pid is None:
        return None
    try:
        import psutil
        return int(psutil.Process(pid).memory_info().rss)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float, default=14400)
    parser.add_argument("--batch-interval-seconds", type=float, default=300)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--once", action="store_true", help="execute one case rotation for preflight")
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.batch_interval_seconds < 30:
        parser.error("duration must be positive and batch interval must be at least 30 seconds")
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    if report_path.exists():
        parser.error(f"report already exists: {report_path}")
    if not all(path.is_file() for path in (LLAMA_SERVER,QWEN_MODEL,QWEN_MMPROJ,ASR_EXE,ASR_MODEL)):
        raise RuntimeError("Qwen CPU or GigaAM fixture/runtime is missing")
    if _port_open(QWEN_PORT):
        raise RuntimeError(f"port {QWEN_PORT} is already owned; refusing to connect to or stop an unknown service")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_root = report_path.parent / (report_path.stem + "-logs")
    log_root.mkdir(parents=True, exist_ok=False)
    stdout_log = (log_root / "qwen.stdout.log").open("wb")
    stderr_log = (log_root / "qwen.stderr.log").open("wb")
    command = [str(LLAMA_SERVER), "-m", str(QWEN_MODEL), "--mmproj", str(QWEN_MMPROJ),
        "--host","127.0.0.1","--port",str(QWEN_PORT),"-c","4096","-np","1","-ngl","0",
        "--no-mmproj-offload","--jinja","--reasoning","off","-t","4","-tb","4",
        "--cache-ram","0","--no-cache-prompt","--no-cache-idle-slots","--metrics"]
    child: subprocess.Popen[bytes] | None = None
    cortex = None
    try:
        child = subprocess.Popen(command, cwd=str(LLAMA_SERVER.parent), stdout=stdout_log, stderr=stderr_log,
                                 creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        ready_deadline = time.monotonic() + 240
        while time.monotonic() < ready_deadline:
            if child.poll() is not None:
                raise RuntimeError(f"owned Qwen server exited early with code {child.returncode}")
            try:
                _json_request(f"http://127.0.0.1:{QWEN_PORT}/health", timeout=2)
                break
            except Exception:
                time.sleep(2)
        else:
            raise TimeoutError("owned Qwen CPU server did not become ready within 240 seconds")

        from jawl_voicecompanion.eg2_sensory import DEFAULT_EG2_ONNX_ROOT, EmbeddingGemmaSensoryCortex
        cortex = EmbeddingGemmaSensoryCortex(DEFAULT_EG2_ONNX_ROOT)
        cases = make_cases()
        report: dict[str, Any] = {
            "schema_version":1,"profile":"sensory_case_simulation","status":"running",
            "scope":"local fixtures; actual Qwen CPU + EmbeddingGemma ONNX + GigaAM CPU; no physical mic/screen capture",
            "started_at":datetime.now(timezone.utc).isoformat(),"duration_requested_seconds":args.duration_seconds,
            "batch_interval_seconds":args.batch_interval_seconds,"case_count":len(cases),
            "qwen":{"pid":child.pid,"port":QWEN_PORT,"cpu_only":True,"threads":4},
            "raw_media_persisted":False,"transcript_text_persisted":False,
            "asr_cadence":"every batch, speech cases only","batches":[],
            "case_totals":{case["id"]:{"runs":0,"errors":0,"latency_ms":[]} for case in cases},
            "errors":[],
        }

        start = time.monotonic()
        batch_number = 0
        while True:
            batch_started = time.monotonic()
            batch_number += 1
            outcomes: list[dict[str, Any]] = []
            asr_due = True
            for case in cases:
                item = {"id":case["id"],"modality":case["modality"],"status":"ok"}
                t0 = time.perf_counter()
                try:
                    if case["modality"] == "vision":
                        image_bytes = case["image"]
                        prompt = "Опиши только достоверно видимые объекты и текущее состояние сцены. Не выводи звук или события, которых не видно. Одно короткое предложение по-русски."
                        payload = {"model":"qwen3.5-0.8b","messages":[{"role":"user","content":[
                            {"type":"text","text":prompt},
                            {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+base64.b64encode(image_bytes).decode("ascii")}}]}],
                            "max_tokens":64,"temperature":0.0,"stream":False}
                        response = _json_request(f"http://127.0.0.1:{QWEN_PORT}/v1/chat/completions",payload,timeout=45)
                        caption = str(response["choices"][0]["message"].get("content") or "").strip()
                        item["caption"] = caption[:240]
                        item["nonempty"] = bool(caption)
                    if case["modality"] in {"audio","audio_visual"}:
                        raw_wav = case.get("wav") or _load_audio(case["wav_path"])
                        obs = cortex.classify_audio_wav(raw_wav)
                        item["audio_tag"] = obs.top_label
                        item["audio_score"] = round(float(obs.top_score),4)
                        item["audio_latency_ms"] = round(float(obs.latency_ms),1)
                        if case.get("image") is not None:
                            fused = cortex.classify_multimodal(case["image"],raw_wav)
                            item["fusion_tag"] = fused.top_label
                            item["scene_changed"] = bool(fused.scene_changed)
                        if case.get("asr"):
                            with tempfile.TemporaryDirectory(prefix="jawl-sensory-case-") as tmp:
                                input_wav = Path(tmp) / "input.wav"; output = Path(tmp) / "asr"
                                input_wav.write_bytes(raw_wav)
                                proc = subprocess.run([str(ASR_EXE),"-m",str(ASR_MODEL),"-oj","-of",str(output),str(input_wav)],
                                    cwd=tmp,capture_output=True,timeout=90)
                                if proc.returncode != 0:
                                    raise RuntimeError("GigaAM ASR returned nonzero status")
                                candidates = [Path(tmp)/"asr.json",Path(tmp)/"asr.wav.json"]
                                data = next((json.loads(p.read_text(encoding="utf-8")) for p in candidates if p.is_file()),None)
                                if data is None:
                                    raise RuntimeError("GigaAM ASR returned no JSON output")
                                trans = data.get("transcription") or data.get("result") or data
                                if isinstance(trans,list): text_value=" ".join(str(x.get("text", "") if isinstance(x,dict) else x) for x in trans)
                                elif isinstance(trans,dict): text_value=str(trans.get("text") or trans.get("transcription") or "")
                                else: text_value=str(trans)
                                item["asr_nonempty"] = bool(text_value.strip())
                                item["asr_chars"] = len(text_value.strip())
                                item["asr_sha256"] = hashlib.sha256(text_value.strip().encode("utf-8")).hexdigest()[:16]
                    if case["modality"] == "contract":
                        from jawl_voicecompanion.ambient_audio import PlaybackSuppression
                        marker = PlaybackSuppression(); begun = marker.begin(1.0); active = marker.active(); ended = marker.end()
                        item["suppression_begin"] = bool(begun.get("active"))
                        item["suppression_active"] = bool(active)
                        item["suppression_end"] = not marker.active() and bool(ended)
                        item["raw_capture"] = False
                        if not item["suppression_begin"] or not item["suppression_active"] or not item["suppression_end"]:
                            raise AssertionError("playback suppression state machine failed")
                except Exception as exc:
                    item["status"] = "error"
                    item["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
                    report["errors"].append({"batch":batch_number,"case":case["id"],"error":item["error"]})
                    report["case_totals"][case["id"]]["errors"] += 1
                item["latency_ms"] = round((time.perf_counter()-t0)*1000,1)
                totals = report["case_totals"][case["id"]]
                totals["runs"] += 1; totals["latency_ms"].append(item["latency_ms"])
                outcomes.append(item)
            batch_elapsed = time.monotonic() - batch_started
            report["batches"].append({"index":batch_number,"elapsed_seconds":round(batch_started-start,1),
                "duration_seconds":round(batch_elapsed,2),"case_count":len(outcomes),
                "passed":sum(x["status"]=="ok" for x in outcomes),"failed":sum(x["status"]!="ok" for x in outcomes),
                "cpu_percent":_cpu_percent(),"qwen_rss_bytes":_process_rss(child.pid),"cases":outcomes})
            report["elapsed_seconds"] = round(time.monotonic()-start,1)
            report["batch_count"] = batch_number
            report["error_count"] = len(report["errors"])
            tmp = report_path.with_suffix(report_path.suffix+".tmp")
            tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); os.replace(tmp,report_path)
            if args.once or time.monotonic()-start >= args.duration_seconds: break
            delay = max(0.0,args.batch_interval_seconds-(time.monotonic()-batch_started))
            time.sleep(delay)
        report["status"] = "passed" if not report["errors"] else "failed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["elapsed_seconds"] = round(time.monotonic()-start,1)
        report["error_count"] = len(report["errors"])
        report["case_totals"] = {key:{"runs":value["runs"],"errors":value["errors"],
            "p50_ms":sorted(value["latency_ms"])[(len(value["latency_ms"])-1)//2] if value["latency_ms"] else None,
            "p95_ms":sorted(value["latency_ms"])[min(len(value["latency_ms"])-1,int((len(value["latency_ms"])-1)*.95))] if value["latency_ms"] else None}
            for key,value in report["case_totals"].items()}
        tmp = report_path.with_suffix(report_path.suffix+".tmp")
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); os.replace(tmp,report_path)
        return 0 if report["status"]=="passed" else 1
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
        stdout_log.close(); stderr_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
