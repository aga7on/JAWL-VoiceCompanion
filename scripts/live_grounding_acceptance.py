"""Live H4-Grounding acceptance: ground, click and verify a real Win32 button.

The script creates its own test window, brings it to the foreground, observes
it through UIA + the screen adapter, turns "Grounding OK" into a strict vision
plan, executes the plan through HostOS policy and verifies the click twice:
once by the window title change and once by the click counter (idempotency).

Run from the repository root on Windows:

    python -X utf8 scripts/live_grounding_acceptance.py

Exit code 0 means every check passed. Nothing outside the test window is
touched; if the window cannot take the foreground, the script aborts instead
of acting on another window.
"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jawl_voicecompanion.grounding import GroundingService  # noqa: E402
from jawl_voicecompanion.hostos_policy import AccessLevel, HostOSPolicy  # noqa: E402
from jawl_voicecompanion.hostos_tools import HostOSExecutor  # noqa: E402
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402
from jawl_voicecompanion.vision import VisionActionPlan, VisionPlanExecutor  # noqa: E402
from jawl_voicecompanion.windows_pointer import WindowsPointerAdapter  # noqa: E402
from jawl_voicecompanion.windows_ui import WindowsUIAutomationAdapter  # noqa: E402

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_TABSTOP = 0x00010000
SW_SHOW = 5
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_LBUTTONDOWN = 0x0201
BN_CLICKED = 0
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
DT_CENTER = 0x00000001
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020
TRANSPARENT = 1

gdi32 = ctypes.windll.gdi32


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

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
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SetWindowTextW.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.SetActiveWindow.restype = wintypes.HWND
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.DrawTextW.argtypes = [
    wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT,
]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


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


class TestWindow:
    """A tiny native window with one button; click count is the postcondition."""

    TITLE = "Grounding Test Window"
    BUTTON = "Grounding OK"
    CLICKED_TITLE = "Grounding OK clicked"
    CANVAS_TEXT = "OCR CANVAS"
    CANVAS_TITLE = "OCR Canvas clicked"

    def __init__(self) -> None:
        self.hwnd = 0
        self.canvas_hwnd = 0
        self.clicks = 0
        self.canvas_clicks = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)
        self._canvas_proc = WNDPROC(self._canvas_wndproc)

    def start(self, timeout: float = 5.0) -> None:
        self._thread = threading.Thread(target=self._run, name="grounding-test-window", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("test window did not start")

    def _run(self) -> None:
        self.thread_id = int(kernel32.GetCurrentThreadId())
        hinstance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinstance
        wc.lpszClassName = "JawlGroundingTestWindow"
        user32.RegisterClassW(ctypes.byref(wc))

        canvas_wc = WNDCLASSW()
        canvas_wc.lpfnWndProc = self._canvas_proc
        canvas_wc.hInstance = hinstance
        canvas_wc.hbrBackground = gdi32.CreateSolidBrush(0xFFFFFF)
        canvas_wc.lpszClassName = "JawlGroundingCanvas"
        user32.RegisterClassW(ctypes.byref(canvas_wc))

        self.hwnd = user32.CreateWindowExW(
            0, wc.lpszClassName, self.TITLE, WS_OVERLAPPEDWINDOW,
            120, 120, 520, 320, None, None, hinstance, None,
        )
        user32.CreateWindowExW(
            0, "BUTTON", self.BUTTON, WS_CHILD | WS_VISIBLE | WS_TABSTOP,
            40, 60, 200, 48, self.hwnd, 1, hinstance, None,
        )
        self.canvas_hwnd = user32.CreateWindowExW(
            0, canvas_wc.lpszClassName, "", WS_CHILD | WS_VISIBLE,
            40, 140, 380, 100, self.hwnd, None, hinstance, None,
        )
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        self._ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND and (int(wparam) & 0xFFFF) == 1:
            self.clicks += 1
            if (int(wparam) >> 16) == BN_CLICKED:
                user32.SetWindowTextW(hwnd, self.CLICKED_TITLE)
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _canvas_wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT:
            paint = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
            client = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(client))
            gdi32.SetBkMode(hdc, TRANSPARENT)
            gdi32.SetTextColor(hdc, 0x000000)
            font = gdi32.CreateFontW(
                -32, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI",
            )
            previous = gdi32.SelectObject(hdc, font)
            user32.DrawTextW(
                hdc, self.CANVAS_TEXT, -1, ctypes.byref(client),
                DT_CENTER | DT_VCENTER | DT_SINGLELINE,
            )
            gdi32.SelectObject(hdc, previous)
            gdi32.DeleteObject(font)
            user32.EndPaint(hwnd, ctypes.byref(paint))
            return 0
        if msg == WM_LBUTTONDOWN:
            self.canvas_clicks += 1
            user32.SetWindowTextW(self.hwnd, self.CANVAS_TITLE)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def focus(self) -> bool:
        user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
        user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
        for _attempt in range(5):
            user32.BringWindowToTop(self.hwnd)
            user32.SetWindowPos(
                self.hwnd, HWND_TOP, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
            foreground = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
            attached = False
            if foreground_thread and foreground_thread != self.thread_id:
                attached = bool(user32.AttachThreadInput(foreground_thread, self.thread_id, True))
            user32.SetActiveWindow(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            if attached:
                user32.AttachThreadInput(foreground_thread, self.thread_id, False)
            time.sleep(0.2)
            if user32.GetForegroundWindow() == self.hwnd:
                return True
            user32.SwitchToThisWindow(self.hwnd, True)
            time.sleep(0.2)
            if user32.GetForegroundWindow() == self.hwnd:
                return True
        return False

    def title(self) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(self.hwnd, buffer, 256)
        return buffer.value

    def close(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


def main() -> int:
    if sys.platform != "win32":
        print(json.dumps({"status": "skipped", "reason": "windows_only"}))
        return 0
    window = TestWindow()
    window.start()
    report: dict[str, object] = {"window": window.TITLE, "button": window.BUTTON}
    try:
        if not window.focus():
            report.update(status="aborted", reason="test_window_cannot_take_foreground")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2

        policy = HostOSPolicy()
        policy.set_access_level(AccessLevel.ROOT)
        executor = HostOSExecutor(
            policy=policy,
            sandbox_root=Path(__file__).resolve().parents[1] / "runtime" / "sandbox",
            ui_automation=WindowsUIAutomationAdapter(),
            screen_capture=ScreenCaptureAdapter(enabled=True, ocr_enabled=True),
            pointer=WindowsPointerAdapter(require_fresh_token=True),
            dry_run=False,
        )
        grounding = GroundingService(uia=executor.ui_automation, screen=executor.screen_capture)
        observation = grounding.observe()
        report["observation"] = {
            "status": observation["status"],
            "candidates": observation["candidate_count"],
            "uia": observation["uia_status"],
            "fresh_token": bool(observation["observation_token"]),
        }
        if observation["status"] != "verified" or not observation["observation_token"]:
            report.update(status="failed", reason="observation_not_verified")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        button = grounding.find(window.BUTTON, observation=observation, limit=1)
        report["match"] = button[0] if button else None
        if not button or button[0]["source"] != "uia":
            report.update(status="failed", reason="button_not_grounded_through_uia")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        planned = grounding.plan(
            "click",
            window.BUTTON,
            observation=observation,
            postcondition={"name": "title_changed", "timeout_ms": 3000},
        )
        report["plan_status"] = planned["status"]
        if planned["status"] != "ok":
            report.update(status="failed", reason=f"plan_{planned['status']}")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        plan = VisionActionPlan.from_dict(planned["plan"])
        report["plan"] = planned["plan"]

        def verify(condition, _result) -> bool:
            name = str(condition.get("name") or "")
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if name == "canvas_clicked":
                    if window.canvas_clicks >= 1 and window.title() == window.CANVAS_TITLE:
                        return True
                elif window.title() == window.CLICKED_TITLE:
                    return True
                time.sleep(0.05)
            return False

        runner = VisionPlanExecutor(executor, postcondition_verifier=verify)
        report["foreground_before_click"] = user32.GetForegroundWindow() == window.hwnd
        first = runner.execute(plan, has_approval=True)
        second = runner.execute(plan, has_approval=True)
        report["first"] = first["status"]
        report["first_actions"] = first.get("actions")
        report["second"] = second["status"]
        report["clicks"] = window.clicks
        report["title_after_button"] = window.title()

        canvas_observation = grounding.observe()
        report["ocr_items"] = canvas_observation["ocr_items"]
        canvas_match = grounding.find(
            window.CANVAS_TEXT, observation=canvas_observation, limit=1,
        )
        report["canvas_match"] = canvas_match[0] if canvas_match else None
        canvas_planned = grounding.plan(
            "click",
            window.CANVAS_TEXT,
            observation=canvas_observation,
            postcondition={"name": "canvas_clicked", "timeout_ms": 3000},
        )
        report["canvas_plan_status"] = canvas_planned["status"]
        canvas_first = canvas_second = {"status": "not_run"}
        if canvas_planned["status"] == "ok":
            canvas_plan = VisionActionPlan.from_dict(canvas_planned["plan"])
            canvas_first = runner.execute(canvas_plan, has_approval=True)
            canvas_second = runner.execute(canvas_plan, has_approval=True)
        report["canvas_first"] = canvas_first["status"]
        report["canvas_first_actions"] = canvas_first.get("actions")
        report["canvas_second"] = canvas_second["status"]
        report["canvas_clicks"] = window.canvas_clicks
        report["title_after_canvas"] = window.title()

        stop_observation = grounding.observe()
        stop_plan_payload = grounding.plan(
            "click",
            window.BUTTON,
            observation=stop_observation,
            postcondition={"name": "title_changed", "timeout_ms": 1000},
        )
        stop_result = {"status": "not_planned"}
        if stop_plan_payload["status"] == "ok":
            stop_plan = VisionActionPlan.from_dict(stop_plan_payload["plan"])
            policy.set_emergency_stop(True, actor="h4_acceptance")
            try:
                stop_result = runner.execute(stop_plan, has_approval=True)
            finally:
                policy.set_emergency_stop(False, actor="h4_acceptance")
        report["stop_status"] = stop_result["status"]
        report["stop_actions"] = stop_result.get("actions")
        report["clicks_after_stop"] = window.clicks

        fresh = grounding.observe()
        missing = grounding.plan("click", "кнопка которой нет", observation=fresh)
        report["missing_target"] = f"{missing['status']}:{missing.get('reason')}"

        ok = (
            first["status"] == "verified"
            and second["status"] == "verified"
            and window.clicks == 1
            and report["title_after_button"] == window.CLICKED_TITLE
            and canvas_match
            and canvas_match[0].get("source") == "ocr"
            and canvas_planned["status"] == "ok"
            and canvas_first["status"] == "verified"
            and canvas_second["status"] == "verified"
            and window.canvas_clicks == 1
            and report["title_after_canvas"] == window.CANVAS_TITLE
            and stop_result["status"] == "denied"
            and window.clicks == 1
            and missing["status"] == "denied"
        )
        report["status"] = "passed" if ok else "failed"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 - acceptance must report, not crash
        report.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    finally:
        window.close()
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
