"""Transient OCR through the OCR engine bundled with Windows.

The adapter receives a Pillow image and returns line-level boxes in image
coordinates. Nothing is written to disk; the image is sent as base64 to a
short-lived PowerShell process that drives Windows.Media.Ocr.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
from typing import Any

_CREATE_NO_WINDOW = 0x08000000

_PS_CODE = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod
})[0]
function Await($op, $type) {
    $m = $asTask.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.GetAwaiter().GetResult()
}

$engines = @()
foreach ($tag in @('ru', 'en-US')) {
    $lang = New-Object Windows.Globalization.Language($tag)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    if ($null -ne $engine) { $engines += $engine }
}

$line = [Console]::In.ReadLine()
if ([string]::IsNullOrWhiteSpace($line)) { exit 0 }
$bytes = [Convert]::FromBase64String($line)
$ras = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$dw = New-Object Windows.Storage.Streams.DataWriter($ras.GetOutputStreamAt(0))
$dw.WriteBytes($bytes)
$null = Await ($dw.StoreAsync()) ([uint32])
$ras.Seek(0)
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
$sbmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$results = @()
foreach ($engine in $engines) {
    $r = Await ($engine.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
    foreach ($l in $r.Lines) {
        $x1 = 1e9; $y1 = 1e9; $x2 = 0; $y2 = 0
        foreach ($w in $l.Words) {
            $b = $w.BoundingRect
            if ($b.X -lt $x1) { $x1 = $b.X }
            if ($b.Y -lt $y1) { $y1 = $b.Y }
            if (($b.X + $b.Width) -gt $x2) { $x2 = $b.X + $b.Width }
            if (($b.Y + $b.Height) -gt $y2) { $y2 = $b.Y + $b.Height }
        }
        if ($x2 -gt $x1 -and $y2 -gt $y1) {
            $results += @{
                text = $l.Text
                x = [int]$x1; y = [int]$y1
                width = [int]($x2 - $x1); height = [int]($y2 - $y1)
            }
        }
    }
}
@{ ok = $true; lines = $results } | ConvertTo-Json -Compress -Depth 4
"""


class WindowsOcr:
    """Callable OCR provider backed by Windows.Media.Ocr."""

    def __init__(self, timeout_s: float = 12.0) -> None:
        self.timeout_s = max(1.0, float(timeout_s))

    def __call__(self, image: Any) -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        payload = base64.b64encode(buffer.getvalue()).decode("ascii")
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_CODE],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_s,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if completed.returncode != 0:
            return []
        lines = self._parse(completed.stdout)
        return lines

    @staticmethod
    def _parse(stdout: str) -> list[dict[str, Any]]:
        payload = ""
        for raw in reversed(str(stdout or "").splitlines()):
            if raw.strip().startswith("{"):
                payload = raw.strip()
                break
        if not payload:
            return []
        try:
            data = json.loads(payload)
        except ValueError:
            return []
        if not isinstance(data, dict) or not data.get("ok"):
            return []
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for raw in data.get("lines") or []:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()[:240]
            try:
                left = int(raw["x"])
                top = int(raw["y"])
                width = int(raw["width"])
                height = int(raw["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if not text or width <= 0 or height <= 0:
                continue
            key = (text.casefold(), left // 8, top // 8)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "text": text,
                    "bbox": [left, top, left + width, top + height],
                    "confidence": 90.0,
                }
            )
            if len(items) >= 64:
                break
        return items
