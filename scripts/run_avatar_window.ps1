[CmdletBinding()]
param(
    [string]$Url = "http://127.0.0.1:8766/avatar?source=pet",
    [int]$Width = 420,
    [int]$Height = 560,
    [int]$Left = 40,
    [int]$Top = 40
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$parsed = [Uri]$Url
if ($parsed.Scheme -notin @("http", "https") -or $parsed.Host -notin @("127.0.0.1", "localhost", "::1") -or $parsed.AbsolutePath -ne "/avatar") {
    throw "Avatar window URL must be a local /avatar HTTP(S) URL."
}
if ($Width -lt 240 -or $Width -gt 2400 -or $Height -lt 240 -or $Height -gt 2400) {
    throw "Avatar window dimensions are outside the bounded range."
}

$request = [System.Net.HttpWebRequest]::Create($Url)
$request.Method = "GET"
$request.Timeout = 3000
$request.ReadWriteTimeout = 3000
$response = $null
try {
    $response = $request.GetResponse()
} catch [System.Net.WebException] {
    $remote = $_.Exception.Response
    if ($remote) {
        $status = [int]$remote.StatusCode
        $remote.Close()
        throw "The avatar URL returned HTTP $status. Start JAWL VoiceCompanion on this port; it may be occupied by a WebSocket-only service."
    }
    throw "The avatar URL is unreachable. Start JAWL VoiceCompanion before launching the avatar window."
}
try {
    if ([int]$response.StatusCode -ne 200 -or $response.ContentType -notlike "text/html*") {
        throw "The avatar URL did not return the expected JAWL HTML page."
    }
} finally {
    $response.Close()
}

if (-not ("JawlAvatar.NativeWindow" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace JawlAvatar {
    public static class NativeWindow {
        private delegate bool EnumWindowsProc(IntPtr handle, IntPtr state);
        [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr state);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr handle);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder text, int length);
        [DllImport("user32.dll", SetLastError = true)] private static extern bool SetWindowPos(IntPtr handle, IntPtr insertAfter, int x, int y, int width, int height, uint flags);

        public static IntPtr FindVisibleTitle(string title) {
            IntPtr found = IntPtr.Zero;
            EnumWindows((handle, state) => {
                if (!IsWindowVisible(handle)) return true;
                var text = new StringBuilder(256);
                GetWindowText(handle, text, text.Capacity);
                if (text.ToString().IndexOf(title, StringComparison.OrdinalIgnoreCase) >= 0) {
                    found = handle;
                    return false;
                }
                return true;
            }, IntPtr.Zero);
            return found;
        }

        public static bool Pin(IntPtr handle, int x, int y, int width, int height) {
            const uint SWP_SHOWWINDOW = 0x0040;
            return SetWindowPos(handle, new IntPtr(-1), x, y, width, height, SWP_SHOWWINDOW);
        }
    }
}
"@
}

$candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe")
)
$browser = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $browser) {
    throw "Microsoft Edge or Google Chrome was not found."
}

$process = Start-Process -FilePath $browser -ArgumentList @(
    "--app=$Url",
    "--window-size=$Width,$Height",
    "--window-position=$Left,$Top"
) -PassThru

$handle = [IntPtr]::Zero
$deadline = [DateTime]::UtcNow.AddSeconds(10)
while ($handle -eq [IntPtr]::Zero -and [DateTime]::UtcNow -lt $deadline) {
    $handle = [JawlAvatar.NativeWindow]::FindVisibleTitle("JAWL Avatar")
    if ($handle -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 100 }
}
if ($handle -eq [IntPtr]::Zero) {
    throw "The avatar window did not become visible within 10 seconds."
}
if (-not [JawlAvatar.NativeWindow]::Pin($handle, $Left, $Top, $Width, $Height)) {
    throw "Windows rejected the always-on-top avatar placement."
}

Write-Host "Avatar window is running above other windows. Close it to finish."
$process.WaitForExit()
