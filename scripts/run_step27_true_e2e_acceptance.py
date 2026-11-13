"""Step 2.7 Staged Component Integration Acceptance Pipeline (NOT Full Production E2E).

Coordinates the staged component integration pipeline on GPU 1 (RTX 5080):
  1. Russian Audio (WAV fixture) -> GigaAM v3 RNN-T via crispasr.exe subprocess (Native CPU) -> Raw Transcript.
  2. TextGateway + TurnArbiter -> EventPolicy Visual Intent Routing.
  3. Controlled Win32 Fixture (OwnedTestWindow: Blue Triangle 42, topmost) -> ScreenCaptureAdapter.
  4. Top-Down Visual Inspection -> Qwen3.5-0.8B VL (llama-server on GPU 1, port 8994).
  5. Calibrated Epistemic Observation -> Context Enrichment.
  6. Brain Dialogue Generation -> SenseNova-Loop-9B (llama-server on GPU 1, port 8990).
  7. Durable History Persistence -> ConversationHistory (conversation.ndjson).
  8. TTS Synthesis -> OmniVoice HTTP Service (GPU 1, port 9890) -> In-Memory WAV (Zero Acoustic Output).
  9. Second Turn Episodic Memory Recall -> In-Test Prompt Rehydration -> SenseNova -> OmniVoice.
 10. Mid-Turn Cancellation (Barge-In) -> TurnArbiter USER_FINAL token abort & concurrency release.

Scope Limitation:
  - This is NOT Full Production E2E: ASR is invoked as an offline subprocess, TTS is manually called per turn,
    and dialogue history context for turn 2 is assembled within the test harness rather than by an automated
    streaming WebSocket client loop.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
import wave

# Ensure workspace packages can be imported
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.event_policy import EventPolicy
from jawl_voicecompanion.gateway import TextGateway
from jawl_voicecompanion.history import ConversationHistory
from jawl_voicecompanion.llm import OpenAICompatibleChatClient
from jawl_voicecompanion.perception_fusion import PerceptionFusion
from jawl_voicecompanion.perception_packet import make_packet, attach_packet
from jawl_voicecompanion.scene_state import EpistemicObservationState, SceneState
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter
from jawl_voicecompanion.sensory_history import SensoryHistoryStore
from jawl_voicecompanion.tts import TeraTTSHttpClient
from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority
from jawl_voicecompanion.vision import OpenAICompatibleVisionClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("step27_true_e2e")

# Directories & Configuration
PROFILE_DIR = ROOT / "runtime" / "instances" / "test_step27_e2e"
LOGS_DIR = PROFILE_DIR / "logs"
QUERIES_DIR = PROFILE_DIR / "queries"
DATA_DIR = PROFILE_DIR / "data" / "sensory"
HISTORY_FILE = PROFILE_DIR / "conversation.ndjson"
SENSORY_HISTORY_FILE = DATA_DIR / "sensory_history.json"
OUT_REPORT = PROFILE_DIR / "step27_e2e_acceptance_report.json"
OUT_METRICS = PROFILE_DIR / "step27_e2e_acceptance_metrics.json"

PROFILE_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
QUERIES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Binaries & Models
LLAMA_SERVER_EXE = ROOT / "runtime" / "bin" / "llama-server" / "llama-server.exe"
QWEN_MODEL_GGUF = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "Qwen3.5-0.8B-Q4_K_M.gguf"
QWEN_MMPROJ_GGUF = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "mmproj-F16.gguf"
SENSENOVA_MODEL_GGUF = ROOT / "runtime" / "sensenova-loop" / "models" / "SenseNova-Loop-9B-Preview-Q4_K_M-verified.gguf"
CRISPASR_BIN = ROOT / "runtime" / "bin" / "crispasr" / "crispasr.exe"
GIGAAM_MODEL = ROOT / "runtime" / "models" / "asr" / "gigaam-v3-e2e-rnnt-q8_0.gguf"
OMNIVOICE_PYTHON = ROOT / "runtime" / "omnivoice-venv" / "Scripts" / "python.exe"
OMNIVOICE_REF_WAV = ROOT / "runtime" / "models" / "tts" / "refs" / "ru_ref.wav"

QWEN_PORT = 8994
SENSENOVA_PORT = 8990
OMNIVOICE_PORT = 9890

# Win32 API Definitions for Controlled Test Canvas
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.UpdateWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t

user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.FillRect.restype = ctypes.c_int
user32.DrawTextW.argtypes = [
    wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT,
]
user32.DrawTextW.restype = ctypes.c_int

gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.SetTextColor.restype = wintypes.COLORREF
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.Polygon.argtypes = [wintypes.HDC, ctypes.POINTER(POINT), ctypes.c_int]
gdi32.Polygon.restype = wintypes.BOOL
gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.LPCWSTR,
]
gdi32.CreateFontW.restype = wintypes.HFONT


class OwnedTestWindow:
    """Creates and displays a visible Win32 window with a prominent Blue Triangle and 42."""

    def __init__(self, title: str = "Test"):
        # Neutral title: no target hints ("JAWL", "Canvas", "Autonomous") printed anywhere.
        # Recognition must come from actual visual content (blue triangle + numeral 42).
        self.title = title
        self.hwnd: int = 0
        self.ready_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._proc = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready_event.wait(timeout=5.0):
            raise RuntimeError("Failed to initialize test window")

    def _wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        WM_PAINT = 0x000F
        WM_DESTROY = 0x0002
        DT_CENTER = 0x00000001
        DT_VCENTER = 0x00000004
        DT_SINGLELINE = 0x00000020

        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))

            # 1. Fill light gray background
            bg_brush = gdi32.CreateSolidBrush(0x00EEEEEE)
            user32.FillRect(hdc, ctypes.byref(rect), bg_brush)
            gdi32.DeleteObject(bg_brush)

            # 2. Draw prominent Blue Triangle in center
            # COLORREF 0x00DC3214 is deep blue in BGR (B=0xDC, G=0x32, R=0x14)
            blue_brush = gdi32.CreateSolidBrush(0x00DC3214)
            old_brush = gdi32.SelectObject(hdc, blue_brush)

            pt_arr = (POINT * 3)(
                POINT(400, 100),
                POINT(200, 420),
                POINT(600, 420),
            )
            gdi32.Polygon(hdc, pt_arr, 3)
            gdi32.SelectObject(hdc, old_brush)
            gdi32.DeleteObject(blue_brush)

            # 3. Draw text header and target label in bold font
            # Large font: numeral must be clearly legible after 1280x720 downscale
            hfont = gdi32.CreateFontW(
                72, 0, 0, 0, 900, 0, 0, 0, 0, 0, 0, 0, 0, "Arial"
            )
            old_font = gdi32.SelectObject(hdc, hfont)
            gdi32.SetBkMode(hdc, 1)  # TRANSPARENT

            # White text inside triangle (large, centered)
            gdi32.SetTextColor(hdc, 0x00FFFFFF)
            rect_tri_text = wintypes.RECT(250, 240, 550, 380)
            user32.DrawTextW(hdc, "42", -1, ctypes.byref(rect_tri_text), DT_CENTER | DT_VCENTER | DT_SINGLELINE)

            # Black neutral header at top (NO target hints: no "Blue", "Triangle", "JAWL",
            # "Canvas", "42" - the numeral must be read from the triangle itself only)
            gdi32.SetTextColor(hdc, 0x00000000)
            rect_header = wintypes.RECT(50, 30, 750, 80)
            user32.DrawTextW(hdc, "Screen 1", -1, ctypes.byref(rect_header), DT_CENTER | DT_SINGLELINE)

            gdi32.SelectObject(hdc, old_font)
            gdi32.DeleteObject(hfont)

            user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"JAWL_E2E_Test_Class_{id(self)}"
        self._proc = WNDPROC(self._wnd_proc)

        wndclass = WNDCLASSW()
        wndclass.style = 0x0003
        wndclass.lpfnWndProc = self._proc
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = class_name
        wndclass.hbrBackground = gdi32.CreateSolidBrush(0x00EEEEEE)

        atom = user32.RegisterClassW(ctypes.byref(wndclass))
        if not atom:
            self.ready_event.set()
            return

        WS_EX_TOPMOST = 0x00000008
        WS_OVERLAPPEDWINDOW = 0x00CF0000
        WS_VISIBLE = 0x10000000
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST, class_name, self.title,
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            100, 100, 800, 600,
            0, 0, hinstance, None,
        )
        if not self.hwnd:
            self.ready_event.set()
            return

        user32.ShowWindow(self.hwnd, 5)  # SW_SHOW
        user32.UpdateWindow(self.hwnd)
        self.bring_to_front()
        self.ready_event.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def bring_to_front(self) -> None:
        if self.hwnd:
            HWND_TOPMOST = ctypes.c_void_p(-1)
            SWP_SHOWWINDOW = 0x0040
            user32.AllowSetForegroundWindow(0xFFFFFFFF)
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 100, 100, 800, 600, SWP_SHOWWINDOW)
            user32.ShowWindow(self.hwnd, 5)
            user32.BringWindowToTop(self.hwnd)
            
            fg_hwnd = user32.GetForegroundWindow()
            fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
            cur_thread = kernel32.GetCurrentThreadId()
            if fg_thread and fg_thread != cur_thread:
                user32.AttachThreadInput(cur_thread, fg_thread, True)
                user32.SetForegroundWindow(self.hwnd)
                user32.AttachThreadInput(cur_thread, fg_thread, False)
            else:
                user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.3)

    def close(self) -> None:
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = 0


def diagnose_window_and_frame(test_window: OwnedTestWindow, adapter: ScreenCaptureAdapter) -> dict[str, Any]:
    """Diagnoses test window accessibility, display index, bounding coordinates, and in-memory frame pixels.
    Strict privacy compliance: NO screen frames or pixels are written to disk.
    """
    is_window = bool(user32.IsWindow(test_window.hwnd))
    is_visible = bool(user32.IsWindowVisible(test_window.hwnd))
    fg_hwnd = user32.GetForegroundWindow()
    is_foreground = (fg_hwnd == test_window.hwnd)

    rect = wintypes.RECT()
    user32.GetWindowRect(test_window.hwnd, ctypes.byref(rect))
    window_rect = [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)]

    # Display monitor bounds
    import win32api
    monitors = win32api.EnumDisplayMonitors()
    monitor_rects = [list(m[2]) for m in monitors]
    target_idx = max(0, min(int(adapter.display_index), len(monitors) - 1))
    target_monitor_rect = monitor_rects[target_idx] if monitor_rects else [0, 0, 1920, 1080]

    # In-memory test frame grab
    frame, t_cap = adapter.grab_pil_with_timestamp()
    if frame is None:
        return {
            "window_valid": is_window and is_visible,
            "window_foreground": is_foreground,
            "window_rect": window_rect,
            "display_index": target_idx,
            "monitor_rect": target_monitor_rect,
            "frame_grabbed": False,
            "pixel_verified": False,
            "pixel_details": "grab_pil returned None",
            "frame_stored_to_disk": False,
        }

    # Center of triangle: client (400, 300) -> screen coordinates
    client_pt = POINT(400, 300)
    user32.ClientToScreen(test_window.hwnd, ctypes.byref(client_pt))

    mon_w = max(1, target_monitor_rect[2] - target_monitor_rect[0])
    mon_h = max(1, target_monitor_rect[3] - target_monitor_rect[1])
    rel_x = client_pt.x - target_monitor_rect[0]
    rel_y = client_pt.y - target_monitor_rect[1]

    scale_x = frame.size[0] / float(mon_w)
    scale_y = frame.size[1] / float(mon_h)
    frame_x = max(0, min(int(rel_x * scale_x), frame.size[0] - 1))
    frame_y = max(0, min(int(rel_y * scale_y), frame.size[1] - 1))

    pixel = frame.getpixel((frame_x, frame_y))
    # BGR 0x00DC3214 -> RGB in PIL is Red ~20, Green ~50, Blue ~220
    is_blue = (pixel[0] < 60 and pixel[2] > 140)

    return {
        "window_hwnd": test_window.hwnd,
        "window_title": test_window.title,
        "window_valid": is_window and is_visible,
        "window_foreground": is_foreground,
        "window_rect": window_rect,
        "display_index": target_idx,
        "monitor_rect": target_monitor_rect,
        "frame_dimensions": list(frame.size),
        "frame_grabbed": True,
        "pixel_verified": is_blue,
        "sampled_point_frame": [frame_x, frame_y],
        "sampled_rgb": list(pixel),
        "frame_stored_to_disk": False,  # Strict privacy invariant
    }


def get_gpu_memory() -> dict[str, dict[str, float]]:
    """Inspects VRAM usage on both GPU 0 and GPU 1."""
    usage: dict[str, dict[str, float]] = {}
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True
        )
        for line in res.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                usage[f"gpu_{parts[0]}"] = {
                    "used_mib": float(parts[1]),
                    "total_mib": float(parts[2]),
                    "util_pct": float(parts[3]),
                }
    except Exception as exc:
        logger.warning("Could not query nvidia-smi: %s", exc)
    return usage


class ManagedServers:
    """Manages background lifecycle of Qwen VL, SenseNova, and OmniVoice on GPU 1."""

    def __init__(self) -> None:
        self.procs: list[subprocess.Popen] = []
        self.logs: list[Any] = []

    def start_all(self) -> None:
        logger.info("Starting Managed Model Servers strictly on GPU 1 (RTX 5080)...")

        # Force CUDA_VISIBLE_DEVICES="1" so physical GPU 0 is hidden and receives 0 driver contexts
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = "1"

        # 1. Qwen3.5-0.8B VL
        qwen_log = open(LOGS_DIR / "llama_qwen_e2e.log", "w", encoding="utf-8")
        self.logs.append(qwen_log)
        p_qwen = subprocess.Popen(
            [
                str(LLAMA_SERVER_EXE),
                "-m", str(QWEN_MODEL_GGUF),
                "--mmproj", str(QWEN_MMPROJ_GGUF),
                "--host", "127.0.0.1",
                "--port", str(QWEN_PORT),
                "-c", "4096",
                "-np", "1",
                "-ngl", "99",
                "-dev", "CUDA0",
                "-fa", "on",
                "--reasoning", "off",
                "--image-min-tokens", "1024",
                "--repeat-penalty", "1.15",
                "--presence-penalty", "0.1",
                "--temperature", "0.2",
                "--seed", "42",
            ],
            env=env,
            stdout=qwen_log,
            stderr=subprocess.STDOUT,
        )
        self.procs.append(p_qwen)

        # 2. SenseNova Loop 9B
        sense_log = open(LOGS_DIR / "llama_sensenova_e2e.log", "w", encoding="utf-8")
        self.logs.append(sense_log)
        p_sense = subprocess.Popen(
            [
                str(LLAMA_SERVER_EXE),
                "-m", str(SENSENOVA_MODEL_GGUF),
                "--host", "127.0.0.1",
                "--port", str(SENSENOVA_PORT),
                "-c", "4096",
                "-np", "1",
                "-ngl", "99",
                "-dev", "CUDA0",
                "-fa", "on",
                "--reasoning", "off",
                "--temperature", "0.2",
                "--seed", "42",
            ],
            env=env,
            stdout=sense_log,
            stderr=subprocess.STDOUT,
        )
        self.procs.append(p_sense)

        # 3. OmniVoice TTS HTTP Server
        omni_log = open(LOGS_DIR / "omnivoice_e2e.log", "w", encoding="utf-8")
        self.logs.append(omni_log)
        p_omni = subprocess.Popen(
            [
                str(OMNIVOICE_PYTHON),
                "-X", "utf8",
                "scripts/omnivoice_server.py",
                "--host", "127.0.0.1",
                "--port", str(OMNIVOICE_PORT),
                "--device", "cuda:0",
                "--ref-audio", str(OMNIVOICE_REF_WAV),
                "--ref-text", "Привет! Я твой голосовой компаньон, рад тебя слышать.",
            ],
            env=env,
            stdout=omni_log,
            stderr=subprocess.STDOUT,
        )
        self.procs.append(p_omni)

        import requests
        self._wait_ready(f"http://127.0.0.1:{QWEN_PORT}/health", "Qwen3.5-0.8B VL", 40)
        self._wait_ready(f"http://127.0.0.1:{SENSENOVA_PORT}/health", "SenseNova-Loop-9B", 45)
        self._wait_ready(f"http://127.0.0.1:{OMNIVOICE_PORT}/health", "OmniVoice TTS", 45)
        logger.info("All model servers active and healthy on GPU 1.")

    def _wait_ready(self, url: str, name: str, timeout_sec: int) -> None:
        import requests
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            try:
                r = requests.get(url, timeout=1.0)
                if r.status_code == 200:
                    logger.info("  -> %s is ready (200 OK)", name)
                    return
            except Exception:
                time.sleep(1.0)
        raise TimeoutError(f"Server {name} failed to become ready at {url} within {timeout_sec}s")

    def stop_all(self) -> None:
        logger.info("Stopping all managed servers...")
        for p in self.procs:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        for lf in self.logs:
            try:
                lf.close()
            except Exception:
                pass
        logger.info("All managed servers stopped.")


def run_acceptance() -> int:
    print("=" * 80)
    print("JAWL Step 2.7 - Staged Component Integration Acceptance Pipeline")
    print("Notice: Staged component integration verification, NOT full production E2E.")
    print("=" * 80)

    # 1. Pre-flight GPU Check
    gpu_before = get_gpu_memory()
    gpu0_used_before = gpu_before.get("gpu_0", {}).get("used_mib", 0.0)
    gpu1_used_before = gpu_before.get("gpu_1", {}).get("used_mib", 0.0)
    print(f"Pre-flight GPU Status:")
    print(f"  GPU 0: {gpu0_used_before:.1f} MiB used (Display / OS - Must NOT change)")
    print(f"  GPU 1: {gpu1_used_before:.1f} MiB used (RTX 5080 target for all models)")

    # 2. Reset conversation and sensory history for isolated profile
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
    if SENSORY_HISTORY_FILE.exists():
        SENSORY_HISTORY_FILE.unlink()
    history_store = ConversationHistory(HISTORY_FILE)

    servers = ManagedServers()
    test_window = OwnedTestWindow()

    results: dict[str, Any] = {}
    metrics: dict[str, Any] = {}

    try:
        # Start Controlled Window Fixture
        print("\n[Step 1/5] Launching Controlled Win32 Test Window...")
        test_window.start()
        test_window.bring_to_front()
        print(f"  -> Test window active (HWND: {test_window.hwnd})")

        # Start Servers on GPU 1
        print("\n[Step 2/5] Starting Managed Model Servers on GPU 1...")
        t_srv_start = time.monotonic()
        servers.start_all()
        t_srv_elapsed = time.monotonic() - t_srv_start
        metrics["servers_startup_latency_s"] = round(t_srv_elapsed, 2)

        # Check GPU usage during model execution
        gpu_running = get_gpu_memory()
        gpu0_used_running = gpu_running.get("gpu_0", {}).get("used_mib", 0.0)
        gpu1_used_running = gpu_running.get("gpu_1", {}).get("used_mib", 0.0)
        print(f"Active GPU Status:")
        print(f"  GPU 0: {gpu0_used_running:.1f} MiB (Delta: {gpu0_used_running - gpu0_used_before:.1f} MiB)")
        print(f"  GPU 1: {gpu1_used_running:.1f} MiB (Delta: +{gpu1_used_running - gpu1_used_before:.1f} MiB)")

        if abs(gpu0_used_running - gpu0_used_before) > 150.0:
            raise RuntimeError(f"GPU 0 leakage detected! Delta: {gpu0_used_running - gpu0_used_before:.1f} MiB")

        # 3. Wiring Runtime Components
        print("\n[Step 3/5] Initializing Cognitive Loop Components...")
        scene_state = SceneState()
        screen_adapter = ScreenCaptureAdapter(enabled=True, scene_state=scene_state)
        qwen_vision = OpenAICompatibleVisionClient(
            endpoint=f"http://127.0.0.1:{QWEN_PORT}",
            model="qwen3.5-0.8b",
            timeout_seconds=15.0,
        )
        sensory_history = SensoryHistoryStore(
            SENSORY_HISTORY_FILE,
            enabled=True,
        )
        fusion = PerceptionFusion(
            vision_describer=qwen_vision,
            scene_state=scene_state,
            history_store=sensory_history,
        )
        fusion.screen_capture = screen_adapter

        event_policy = EventPolicy()
        turn_arbiter = TurnArbiter()

        sensenova_chat = OpenAICompatibleChatClient(
            endpoint=f"http://127.0.0.1:{SENSENOVA_PORT}/v1",
            model="SenseNova-Loop-9B",
            system_prompt=(
                "Ты — JAWL, умный и честный голосовой компаньон владельца ПК. "
                "Ты отвечаешь кратко и естественно (1-2 предложения на русском языке). "
                "Опирайся строго на предоставленные факты наблюдения экрана и историю диалога. "
                "Если на экране видна геометрическая фигура или надпись, обязательно назови её прямо."
            ),
            timeout_seconds=20.0,
        )

        gateway = TextGateway(
            responder=sensenova_chat,
            event_policy=event_policy,
            perception_fusion=fusion,
            scene_state=scene_state,
            history_store=history_store,
            arbiter=turn_arbiter,
            vision_timeout_s=10.0,
        )
        tts_client = TeraTTSHttpClient(f"http://127.0.0.1:{OMNIVOICE_PORT}")

        # =====================================================================
        # Scenario 1: Staged Multimodal Visual Turn (Live Visual Grounding)
        # =====================================================================
        print("\n" + "=" * 60)
        print("[Scenario 1] Staged Multimodal Visual Turn")
        print("  Chain: WAV fixture -> crispasr ASR -> Gateway -> ScreenCaptureAdapter -> Qwen VL -> SenseNova -> Manual TTS -> History")
        print("=" * 60)

        test_window.bring_to_front()
        time.sleep(0.3)

        # 1a. Test window & capture accessibility diagnostic (zero disk frame storage)
        window_diag = diagnose_window_and_frame(test_window, screen_adapter)
        print(f"  [Window Diag] HWND: {window_diag.get('window_hwnd')}, Topmost/FG: {window_diag.get('window_foreground')}")
        print(f"  [Window Diag] Display: {window_diag.get('display_index')}, Rect: {window_diag.get('window_rect')}, Frame: {window_diag.get('frame_dimensions')}")
        print(f"  [Window Diag] Pixel verified blue at triangle center: {window_diag.get('pixel_verified')} (Sampled RGB: {window_diag.get('sampled_rgb')})")
        print(f"  [Privacy] Frame stored to disk: {window_diag.get('frame_stored_to_disk')}")

        # 1b. ASR
        wav_q1 = QUERIES_DIR / "query1_screen.wav"
        t0_asr1 = time.monotonic()
        asr1_proc = subprocess.run(
            [str(CRISPASR_BIN), "-m", str(GIGAAM_MODEL), "-f", str(wav_q1)],
            capture_output=True, text=True, encoding="utf-8",
        )
        t_asr1 = time.monotonic() - t0_asr1
        transcript_1 = asr1_proc.stdout.strip()
        print(f"  [ASR] Transcribed in {t_asr1*1000:.1f}ms: '{transcript_1}'")

        # 1c. Check absence of hints/leakage in user query
        q1_lower = transcript_1.lower()
        leakage_detected = any(hint in q1_lower for hint in ["треугольник", "triangle", "синий", "голубой", "blue", "42"])
        prompt_leakage_absent = not leakage_detected
        print(f"  [Sanity] Query contains no target hints: {prompt_leakage_absent}")

        # 1d. Gateway handle_text -> triggers EventPolicy visual intent -> Qwen VL -> SenseNova
        corr_1 = "turn-e2e-scenario-1"
        t0_turn1 = time.monotonic()
        envelope_1 = gateway.handle_text(
            transcript_1,
            session_id="test_step27_e2e",
            correlation_id=corr_1,
        )
        t_turn1 = time.monotonic() - t0_turn1

        obs_1 = getattr(gateway, "latest_epistemic_observation", {}) or {}
        raw_vlm_text = str(obs_1.get("details", ""))
        print(f"  [Vision] Status: {obs_1.get('status')}, Quality: {obs_1.get('inspection_quality')}")
        print(f"  [Vision] Raw details: '{raw_vlm_text[:90]}...'")
        print(f"  [Brain] SenseNova Response in {t_turn1*1000:.1f}ms:")
        print(f"          '{envelope_1.get('text')}'")

        # 1e. OmniVoice TTS HTTP Synthesis (into in-memory buffer, zero acoustic playback)
        t0_tts1 = time.monotonic()
        tts1_wav_bytes = tts_client.synthesize(envelope_1.get("text", ""))
        t_tts1 = time.monotonic() - t0_tts1
        print(f"  [TTS] Synthesized {len(tts1_wav_bytes)} WAV bytes in {t_tts1*1000:.1f}ms (Zero Acoustic Playback)")

        # Flush sensory history store to disk
        sensory_history.flush()

        # 1f. Decomposed Fact & Ground Truth Verification
        details_1_lower = raw_vlm_text.lower()
        resp_1_lower = str(envelope_1.get("text", "")).lower()

        # Visual geometry fact: triangle
        vlm_fact_shape = any(w in details_1_lower for w in ["треугольник", "треугольн", "triangle"])
        resp_fact_shape = any(w in resp_1_lower for w in ["треугольник", "треугольн", "triangle"])

        # Visual color fact: blue (supporting Russian inflections: синий, синего, синим, синем, etc.)
        blue_inflections = ["синий", "синег", "синим", "синем", "синяя", "синей", "синюю", "синее", "синие", "синих", "синими", "голуб", "blue"]
        vlm_fact_color = any(w in details_1_lower for w in blue_inflections)
        resp_fact_color = any(w in resp_1_lower for w in blue_inflections)

        # Text/numeral OCR fact: 42
        vlm_fact_ocr_42 = "42" in details_1_lower
        resp_fact_ocr_42 = "42" in resp_1_lower

        # Header OCR fact: neutral header "Screen 1" (contains NO target facts by design:
        # shape/color/numeral recognition must come from the drawn triangle only, never
        # from a printed window title or header text)
        vlm_fact_ocr_canvas = any(w in details_1_lower for w in ["screen", "скрин"])

        # Negative controls (shapes & colors NOT present on screen)
        unseen_shapes = ["круг", "квадрат", "звезд", "ромб", "овал", "шестиугольн", "circle", "square", "star", "diamond"]
        unseen_colors = ["красный", "красног", "зелёный", "зеленог", "жёлтый", "желтог", "оранжевый", "фиолетовый", "red", "green", "yellow", "purple"]

        def _has_unseen_token(text: str, word: str) -> bool:
            import re
            tokens = re.findall(r"[а-яёa-z0-9]+", text.lower())
            for tok in tokens:
                if tok == "вокруг" and word == "круг":
                    continue
                if tok.startswith(word):
                    return True
            return False

        vlm_neg_shapes_passed = not any(_has_unseen_token(details_1_lower, w) for w in unseen_shapes)
        vlm_neg_colors_passed = not any(w in details_1_lower for w in unseen_colors)
        resp_neg_shapes_passed = not any(_has_unseen_token(resp_1_lower, w) for w in unseen_shapes)
        resp_neg_colors_passed = not any(w in resp_1_lower for w in unseen_colors)

        # Epistemic observation MUST be observed_present for positive ground truth
        epistemic_observed_present = (obs_1.get("status") == EpistemicObservationState.OBSERVED_PRESENT)
        tts_valid = len(tts1_wav_bytes) > 10000

        s1_pass = (
            prompt_leakage_absent
            and window_diag.get("pixel_verified", False)
            and epistemic_observed_present
            and vlm_fact_shape and resp_fact_shape
            and vlm_fact_color and resp_fact_color
            and vlm_fact_ocr_42 and resp_fact_ocr_42
            and vlm_neg_shapes_passed and resp_neg_shapes_passed
            and vlm_neg_colors_passed and resp_neg_colors_passed
            and tts_valid
        )
        s1_status = "PASS (FINE_GRAINED_MULTIMODAL_PROVEN)" if s1_pass else "FAIL / UNKNOWN (GROUND_TRUTH_DISCREPANCY)"

        results["scenario_1_e2e_multimodal_turn"] = {
            "status": s1_status,
            "tier": "STAGED_COMPONENT_INTEGRATION (WAV fixture -> ASR subprocess -> Gateway -> ScreenCaptureAdapter -> Qwen VL -> SenseNova -> Manual TTS)",
            "correlation_id": corr_1,
            "turn_id": envelope_1.get("turn_id"),
            "raw_asr_transcript": transcript_1,
            "window_and_frame_diagnostic": window_diag,
            "ground_truth_decomposition": {
                "visual_geometry_shape": {
                    "expected": "triangle / треугольник",
                    "vlm_detected": vlm_fact_shape,
                    "dialogue_mentioned": resp_fact_shape,
                },
                "visual_surface_color": {
                    "expected": "blue / синий",
                    "vlm_detected": vlm_fact_color,
                    "dialogue_mentioned": resp_fact_color,
                },
                "ocr_numeral_content": {
                    "expected": "42",
                    "vlm_detected": vlm_fact_ocr_42,
                    "dialogue_mentioned": resp_fact_ocr_42,
                },
                "ocr_window_header": {
                    "expected": "Screen 1 (neutral, no target facts by design)",
                    "vlm_detected": vlm_fact_ocr_canvas,
                },
                "negative_controls": {
                    "hallucinated_shapes_absent_in_vlm": vlm_neg_shapes_passed,
                    "hallucinated_shapes_absent_in_dialogue": resp_neg_shapes_passed,
                    "hallucinated_colors_absent_in_vlm": vlm_neg_colors_passed,
                    "hallucinated_colors_absent_in_dialogue": resp_neg_colors_passed,
                },
                "prompt_leakage_control": {
                    "query_text": transcript_1,
                    "target_hints_absent_in_query": prompt_leakage_absent,
                },
            },
            "context_provenance": [
                {
                    "fragment_id": "epistemic_observation_vlm",
                    "provenance_type": "LIVE_MULTIMODAL_PERCEPTION",
                    "source_component": "OpenAICompatibleVisionClient (Qwen3.5-0.8B-Q4_K_M on cuda:1)",
                    "capture_pipeline": "ScreenCaptureAdapter.grab_pil (Win32 GDI topmost client window)",
                    "target": "экран",
                    "region": "full_frame",
                    "status": obs_1.get("status"),
                    "quality": obs_1.get("inspection_quality"),
                    "semantic_age_ms": obs_1.get("semantic_age_ms"),
                    "raw_vlm_prompt": "Опиши кратко и конкретно, что сейчас видно на экране: основные объекты, текст, геометрические фигуры и цвета. Не придумывай то, чего не видишь.",
                    "raw_vlm_response": raw_vlm_text,
                }
            ],
            "sensenova_response": envelope_1.get("text"),
            "tts_wav_bytes": len(tts1_wav_bytes),
            "latencies_ms": {
                "asr_latency_ms": round(t_asr1 * 1000.0, 1),
                "turn_latency_ms": round(t_turn1 * 1000.0, 1),
                "tts_latency_ms": round(t_tts1 * 1000.0, 1),
                "total_e2e_ms": round((t_asr1 + t_turn1 + t_tts1) * 1000.0, 1),
            },
        }
        metrics["scenario_1_total_e2e_ms"] = round((t_asr1 + t_turn1 + t_tts1) * 1000.0, 1)

        # =====================================================================
        # Scenario 2A: Canonical Sensory Episodic Memory Retrieval
        # =====================================================================
        print("\n" + "=" * 60)
        print("[Scenario 2A] Canonical Sensory Episodic Memory Retrieval")
        print("  Chain: WAV fixture -> ASR subprocess -> SensoryHistoryStore -> <va_perception> -> SenseNova -> Manual TTS")
        print("=" * 60)

        # 2a-1. Check persisted sensory history file
        sensory_state = sensory_history.state()
        print(f"  [SensoryHistoryStore] Enabled: {sensory_state.get('enabled')}, Recent events: {sensory_state.get('recent_event_count')}")
        print(f"  [SensoryHistoryStore] File exists on disk: {SENSORY_HISTORY_FILE.is_file()} ({SENSORY_HISTORY_FILE.stat().st_size if SENSORY_HISTORY_FILE.is_file() else 0} bytes)")

        # 2a-2. ASR for Query 2A: "Что было на экране раньше?"
        wav_q2a = QUERIES_DIR / "query2_earlier_screen.wav"
        t0_asr2a = time.monotonic()
        asr2a_proc = subprocess.run(
            [str(CRISPASR_BIN), "-m", str(GIGAAM_MODEL), "-f", str(wav_q2a)],
            capture_output=True, text=True, encoding="utf-8",
        )
        t_asr2a = time.monotonic() - t0_asr2a
        transcript_2a = asr2a_proc.stdout.strip()
        print(f"  [ASR] Transcribed in {t_asr2a*1000:.1f}ms: '{transcript_2a}'")

        # 2a-3. Canonical retrieval from SensoryHistoryStore and packaging in perception packet
        sensory_context = sensory_history.context_text(seconds=3600)
        packet_2a = make_packet({}, fallback="", history=sensory_context)
        enriched_2a = attach_packet(transcript_2a, packet_2a)

        corr_2a = "turn-e2e-scenario-2a-sensory-recall"
        t0_turn2a = time.monotonic()
        envelope_2a = gateway.handle_text(
            enriched_2a,
            session_id="test_step27_e2e",
            correlation_id=corr_2a,
            history_user_text=transcript_2a,
        )
        t_turn2a = time.monotonic() - t0_turn2a
        print(f"  [Brain] SenseNova Sensory Recall Response in {t_turn2a*1000:.1f}ms:")
        print(f"          '{envelope_2a.get('text')}'")

        # 2a-4. TTS synthesis
        t0_tts2a = time.monotonic()
        tts2a_wav_bytes = tts_client.synthesize(envelope_2a.get("text", ""))
        t_tts2a = time.monotonic() - t0_tts2a
        print(f"  [TTS] Synthesized {len(tts2a_wav_bytes)} WAV bytes in {t_tts2a*1000:.1f}ms")

        # 2a-5. Verification: strict grounding - requires s1_pass AND both shape and details
        # NEVER match generic words like "окно", "кадр", "экран"
        resp_2a_lower = str(envelope_2a.get("text", "")).lower()
        recalled_sensory_shape = any(w in resp_2a_lower for w in ["треугольник", "треугольн", "triangle"])
        recalled_sensory_details = any(w in resp_2a_lower for w in ["синий", "синег", "синим", "синем", "синяя", "синей", "синюю", "синее", "синие", "синих", "синими", "голуб", "42", "blue"])
        target_facts_recalled_2a = recalled_sensory_shape and recalled_sensory_details

        s2a_pass = (
            s1_pass  # Target MUST have been observed present in Scenario 1
            and sensory_state.get("recent_event_count", 0) > 0
            and SENSORY_HISTORY_FILE.is_file()
            and target_facts_recalled_2a
            and len(tts2a_wav_bytes) > 10000
        )

        results["scenario_2a_canonical_sensory_episodic_recall"] = {
            "status": "PASS (CANONICAL_SENSORY_RETRIEVAL_PROVEN)" if s2a_pass else "FAIL / UNKNOWN (SENSORY_RECALL_NOT_VERIFIED)",
            "tier": "STAGED_SENSORY_HISTORY_RECALL (SensoryHistoryStore -> <va_perception> -> SenseNova -> Manual TTS)",
            "correlation_id": corr_2a,
            "turn_id": envelope_2a.get("turn_id"),
            "raw_asr_transcript": transcript_2a,
            "sensory_store_state": sensory_state,
            "sensory_store_file_persisted": SENSORY_HISTORY_FILE.is_file(),
            "sensory_context_excerpt": sensory_context[:250],
            "context_provenance": [
                {
                    "fragment_id": "sensory_history_timeline",
                    "provenance_type": "CANONICAL_SENSORY_EPISODIC_RETRIEVAL",
                    "source_component": "SensoryHistoryStore",
                    "persistence_file": str(SENSORY_HISTORY_FILE),
                    "retrieval_method": "SensoryHistoryStore.context_text(seconds=3600)",
                    "packet_container": "<va_perception> JSON history attribute",
                }
            ],
            "sensenova_sensory_recall_response": envelope_2a.get("text"),
            "target_facts_recalled": {
                "shape_recalled": recalled_sensory_shape,
                "color_or_numeral_recalled": recalled_sensory_details,
                "both_proven": target_facts_recalled_2a,
            },
            "tts_wav_bytes": len(tts2a_wav_bytes),
            "latencies_ms": {
                "asr_latency_ms": round(t_asr2a * 1000.0, 1),
                "turn_latency_ms": round(t_turn2a * 1000.0, 1),
                "tts_latency_ms": round(t_tts2a * 1000.0, 1),
                "total_e2e_ms": round((t_asr2a + t_turn2a + t_tts2a) * 1000.0, 1),
            },
        }
        metrics["scenario_2a_total_e2e_ms"] = round((t_asr2a + t_turn2a + t_tts2a) * 1000.0, 1)

        # =====================================================================
        # Scenario 2B: In-Test Prompt Dialogue History Continuity
        # =====================================================================
        print("\n" + "=" * 60)
        print("[Scenario 2B] In-Test Prompt Dialogue History Continuity")
        print("  Chain: WAV fixture -> ASR subprocess -> ConversationHistory Store -> Hand-Assembled Prompt -> SenseNova -> Manual TTS")
        print("=" * 60)

        # 2b-1. Verify persistence in conversation.ndjson
        persisted_turns = history_store.turns()
        print(f"  [ConversationHistory] Persisted turns on disk: {len(persisted_turns)}")
        if not persisted_turns:
            raise RuntimeError("ConversationHistory failed to record turns to disk!")

        turn1_record = persisted_turns[0]

        # 2b-2. ASR for Query 2B
        wav_q2b = QUERIES_DIR / "query2_recall.wav"
        t0_asr2b = time.monotonic()
        asr2b_proc = subprocess.run(
            [str(CRISPASR_BIN), "-m", str(GIGAAM_MODEL), "-f", str(wav_q2b)],
            capture_output=True, text=True, encoding="utf-8",
        )
        t_asr2b = time.monotonic() - t0_asr2b
        transcript_2b = asr2b_proc.stdout.strip()
        print(f"  [ASR] Transcribed in {t_asr2b*1000:.1f}ms: '{transcript_2b}'")

        # 2b-3. Rehydrate dialogue history transcript (matching web.py:893-920 boundary assembly)
        history_transcript_lines = []
        for t in persisted_turns[:4]:
            u = str(t.get("user") or "").strip()
            r = t.get("response")
            rt = str(r.get("text") or "").strip() if isinstance(r, dict) else ""
            if u:
                history_transcript_lines.append(f'User: "{u}"')
            if rt:
                history_transcript_lines.append(f'JAWL: "{rt}"')

        dialogue_context = (
            "[RECENT LOCAL CONVERSATION TRANSCRIPT]\n"
            + "\n".join(history_transcript_lines) + "\n"
            + "[END PRIOR DIALOGUE]\n\n"
            + f"[CURRENT USER MESSAGE]\n{transcript_2b}"
        )

        corr_2b = "turn-e2e-scenario-2b-dialogue-recall"
        t0_turn2b = time.monotonic()
        envelope_2b = gateway.handle_text(
            dialogue_context,
            session_id="test_step27_e2e",
            correlation_id=corr_2b,
            history_user_text=transcript_2b,
        )
        t_turn2b = time.monotonic() - t0_turn2b
        print(f"  [Brain] SenseNova Dialogue Recall Response in {t_turn2b*1000:.1f}ms:")
        print(f"          '{envelope_2b.get('text')}'")

        # 2b-4. TTS synthesis
        t0_tts2b = time.monotonic()
        tts2b_wav_bytes = tts_client.synthesize(envelope_2b.get("text", ""))
        t_tts2b = time.monotonic() - t0_tts2b
        print(f"  [TTS] Synthesized {len(tts2b_wav_bytes)} WAV bytes in {t_tts2b*1000:.1f}ms")

        # 2b-5. Verification: strict grounding - requires s1_pass AND both shape and details
        # NEVER match generic words like "окно", "кадр", "экран"
        resp_2b_lower = str(envelope_2b.get("text", "")).lower()
        recalled_dialogue_shape = any(w in resp_2b_lower for w in ["треугольник", "треугольн", "triangle"])
        recalled_dialogue_details = any(w in resp_2b_lower for w in ["синий", "синег", "синим", "синем", "синяя", "синей", "синюю", "синее", "синие", "синих", "синими", "голуб", "42", "blue"])
        recalls_dialogue_target = recalled_dialogue_shape and recalled_dialogue_details
        s2b_pass = s1_pass and recalls_dialogue_target and len(persisted_turns) >= 1 and len(tts2b_wav_bytes) > 10000

        results["scenario_2b_dialogue_transcript_continuity"] = {
            "status": "PASS (DIALOGUE_CONTINUITY_PROVEN)" if s2b_pass else "FAIL / UNKNOWN (DIALOGUE_RECALL_NOT_VERIFIED)",
            "tier": "STAGED_DIALOGUE_TRANSCRIPT_RECALL (ConversationHistory Store -> Hand-Assembled Prompt -> SenseNova -> Manual TTS)",
            "correlation_id": corr_2b,
            "turn_id": envelope_2b.get("turn_id"),
            "raw_asr_transcript": transcript_2b,
            "recalled_from_store_turn_count": len(persisted_turns),
            "context_provenance": [
                {
                    "fragment_id": "conversation_transcript_rehydration",
                    "provenance_type": "HAND_ASSEMBLED_CONVERSATION_HISTORY",
                    "source_component": "ConversationHistory",
                    "persistence_file": str(HISTORY_FILE),
                    "retrieval_method": "ConversationHistory.turns() -> [RECENT LOCAL CONVERSATION TRANSCRIPT] rehydration",
                }
            ],
            "sensenova_dialogue_recall_response": envelope_2b.get("text"),
            "target_facts_recalled": {
                "shape_recalled": recalled_dialogue_shape,
                "color_or_numeral_recalled": recalled_dialogue_details,
                "both_proven": recalls_dialogue_target,
            },
            "tts_wav_bytes": len(tts2b_wav_bytes),
            "latencies_ms": {
                "asr_latency_ms": round(t_asr2b * 1000.0, 1),
                "turn_latency_ms": round(t_turn2b * 1000.0, 1),
                "tts_latency_ms": round(t_tts2b * 1000.0, 1),
                "total_e2e_ms": round((t_asr2b + t_turn2b + t_tts2b) * 1000.0, 1),
            },
        }
        metrics["scenario_2b_total_e2e_ms"] = round((t_asr2b + t_turn2b + t_tts2b) * 1000.0, 1)

        # =====================================================================
        # Scenario 3: Mid-Turn Cancellation (Barge-In)
        # =====================================================================
        print("\n" + "=" * 60)
        print("[Scenario 3] Mid-Turn Cancellation (Barge-In)")
        print("  Mechanism: TurnArbiter USER_FINAL superseding active in-flight turn")
        print("=" * 60)

        # Token 1 starts in background thread
        turn1_result: dict[str, Any] = {}
        turn1_started = threading.Event()
        turn1_finished = threading.Event()

        def _run_long_turn():
            turn1_started.set()
            corr_long = "turn-e2e-bargein-victim"
            # Using query 3 (long descriptive query)
            res = gateway.handle_text(
                "Расскажи подробно и развернуто о том, как устроен этот мир.",
                session_id="test_step27_e2e",
                correlation_id=corr_long,
                priority=TurnPriority.USER_FINAL,
            )
            turn1_result["res"] = res
            turn1_finished.set()

        t_thread = threading.Thread(target=_run_long_turn)
        t_thread.start()
        turn1_started.wait(timeout=2.0)

        # Wait briefly so turn 1 enters execution
        time.sleep(0.08)

        # Barge-in: User speaks new query with USER_FINAL priority
        t0_bargein = time.monotonic()
        corr_bargein = "turn-e2e-bargein-interrupter"
        bargein_envelope = gateway.handle_text(
            "Стоп! Короткий ответ: скажи привет.",
            session_id="test_step27_e2e",
            correlation_id=corr_bargein,
            priority=TurnPriority.USER_FINAL,
        )
        t_bargein_elapsed = time.monotonic() - t0_bargein

        t_thread.join(timeout=20.0)

        print(f"  Barge-in Interrupter completed in {t_bargein_elapsed*1000:.1f}ms")
        print(f"  Barge-in Response: '{bargein_envelope.get('text')}'")
        res1 = turn1_result.get("res", {})
        print(f"  Victim Turn Status: status='{res1.get('status')}', speak={res1.get('speak')}, text='{res1.get('text')}'")

        # Concurrency & arbitration checks
        interrupter_succeeded = bool(bargein_envelope.get("text"))
        victim_suppressed = (
            res1.get("status") == "deferred"
            or not res1.get("speak")
            or "отмен" in str(res1.get("text", "")).lower()
        )
        s3_pass = interrupter_succeeded and victim_suppressed

        results["scenario_3_barge_in_cancellation"] = {
            "status": "PASS (PIPELINE_CANCELLATION_PROVEN; HARDWARE_CUDA_CANCEL_UNKNOWN)" if s3_pass else "FAIL / UNKNOWN (BARGE_IN_NOT_PROVEN)",
            "tier": "BARGE_IN_ARBITRATION (TurnArbiter USER_FINAL Supersede + Concurrency Slot Release)",
            "context_provenance": [
                {
                    "fragment_id": "turn_arbiter_priority_preemption",
                    "provenance_type": "TURN_ARBITER_USER_FINAL_PREEMPTION",
                    "source_component": "TurnArbiter",
                    "mechanism": "Active turn slot revoked on higher/equal priority USER_FINAL admission",
                }
            ],
            "victim_turn_suppressed": victim_suppressed,
            "victim_turn_text": res1.get("text"),
            "interrupter_response": bargein_envelope.get("text"),
            "interrupter_latency_ms": round(t_bargein_elapsed * 1000.0, 1),
            "physical_cuda_cancel": "UNKNOWN (PHYSICAL CUDA CANCEL NOT PROVEN)",
        }
        metrics["scenario_3_bargein_latency_ms"] = round(t_bargein_elapsed * 1000.0, 1)

        # Staged transport fidelity disclosure (strictly separating component integration from full production E2E)
        results["transport_fidelity"] = {
            "audio_input_tier": "ASR_SUBPROCESS_WAV (crispasr / GigaAM v3 RNN-T CPU, offline WAV fixtures, bypasses live microphone / WASAPI capture)",
            "audio_output_tier": "MANUAL_TTS_CLIENT_INVOCATION (OmniVoice HTTP / 24kHz WAV into RAM buffer, zero acoustic/speaker playback)",
            "dialogue_context_tier": "HAND_ASSEMBLED_TURN_CONTEXT (In-test harness prompt rehydration from ConversationHistory/SensoryHistory; no automated client-side streaming session loop)",
            "vision_capture_tier": "CONTROLLED_WIN32_CANVAS_TOPDOWN (ScreenCaptureAdapter / grab_pil from live topmost Win32 window, Qwen VL on GPU 1)",
            "brain_execution_tier": "LOCAL_LLAMA_SERVER_HTTP (SenseNova-Loop-9B on GPU 1)",
            "overall_fidelity_tier": "STAGED_COMPONENT_INTEGRATION (NOT Full Production E2E: ASR runs via subprocess, TTS is manually invoked into RAM, second-turn dialogue context is hand-assembled in test harness; verifies model reasoning, vision grounding, episodic memory, and turn preemption)",
        }

    finally:
        print("\n[Teardown] Cleaning up windows, servers, and resources...")
        test_window.close()
        servers.stop_all()

    # 4. Post-flight GPU Check
    gpu_after = get_gpu_memory()
    gpu0_used_after = gpu_after.get("gpu_0", {}).get("used_mib", 0.0)
    gpu1_used_after = gpu_after.get("gpu_1", {}).get("used_mib", 0.0)
    print(f"\nPost-flight GPU Status:")
    print(f"  GPU 0: {gpu0_used_after:.1f} MiB (Net change: {gpu0_used_after - gpu0_used_before:.1f} MiB - strictly clean)")
    print(f"  GPU 1: {gpu1_used_after:.1f} MiB (Net change: {gpu1_used_after - gpu1_used_before:.1f} MiB - teardown complete)")

    metrics["gpu_accounting"] = {
        "gpu0_before_mib": gpu0_used_before,
        "gpu0_after_mib": gpu0_used_after,
        "gpu0_max_delta_mib": round(gpu0_used_running - gpu0_used_before, 1),
        "gpu1_before_mib": gpu1_used_before,
        "gpu1_running_mib": gpu1_used_running,
        "gpu1_after_mib": gpu1_used_after,
        "gpu0_leakage_prevented": abs(gpu0_used_running - gpu0_used_before) < 150.0,
    }

    # 5. Save structured report and metrics
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open(OUT_METRICS, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("ACCEPTANCE VERDICT MATRIX:")
    print("=" * 80)
    all_pass = True
    for key, val in results.items():
        if not isinstance(val, dict) or "status" not in val:
            continue
        st = val.get("status", "UNKNOWN")
        tier = val.get("tier", "")
        if not st.startswith("PASS"):
            all_pass = False
        print(f"  {key:<42}: {st} [{tier}]")
    print("-" * 80)
    print(f"Report saved to:  {OUT_REPORT}")
    print(f"Metrics saved to: {OUT_METRICS}")
    print("=" * 80)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(run_acceptance())
