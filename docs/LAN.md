# Tablet/LAN access

LAN access is an explicit deployment mode. The default launcher remains
loopback-only (`127.0.0.1:2367` control and `127.0.0.1:8766` presentation).
Remote control binds are rejected unless `--lan` is present, a private or
unspecified bind address is selected, HTTPS has a certificate and private key,
and a process-local LAN access token is configured.

The control surface uses two checks:

1. HTTP Basic authentication challenges the browser before it serves the UI or
   any control API. The password is read from `JAWL_LAN_TOKEN` (or the
   environment variable named by `--lan-auth-token-env`) and is never a
   command-line argument.
2. The existing session cookie plus CSRF token still protect control routes.
   Browser requests with an `Origin` header must match the HTTPS origin and
   request `Host` exactly, including the port. Basic auth does not bypass
   session, CSRF, or origin checks.

The separate presentation server stays read-only and does not receive control
credentials. It remains loopback by default. If it is deliberately moved to a
LAN address with `--presentation-host`, it also requires `--lan` and the same
certificate pair, but it still exposes only the bounded avatar state.

## 1. Create or obtain a certificate

Use a certificate whose Subject Alternative Name contains the exact IP address
or DNS name that the tablet will open. Keep the private key outside the
repository and do not copy it to the tablet. For a temporary private-LAN
certificate, OpenSSL can create a PEM pair (run from a protected directory):

```powershell
openssl req -x509 -newkey rsa:2048 -nodes -days 30 `
  -keyout jawl-lan.key -out jawl-lan.crt `
  -subj "/CN=192.168.1.23" `
  -addext "subjectAltName=IP:192.168.1.23"
```

Replace `192.168.1.23` with the PC's private LAN address. If using a local DNS
name instead, put `DNS:jawl.lan` in the SAN and open that same name on the
tablet. A certificate for `localhost` or `127.0.0.1` is not valid for the LAN
address.

This short 30-day certificate is for a local demo; renew it when it expires.
A managed/local-CA certificate may be required by your device policy.

Before using the tablet, install the public `jawl-lan.crt` in the tablet's
trusted certificate store/browser trust path and confirm that the browser
shows no certificate warning. Never install or transfer `jawl-lan.key`.
This trust step and manual tablet check remain pending in this repository.

## 2. Start the authenticated control surface

Set the token only in the environment of the launcher. Use at least 16 random
characters; do not put it in the URL, PowerShell command history, or process
arguments.

```powershell
$lanIp = '192.168.1.23'
$secureToken = Read-Host 'LAN access token (16+ characters)' -AsSecureString
$lanCredential = New-Object System.Management.Automation.PSCredential('tablet', $secureToken)
$env:JAWL_LAN_TOKEN = $lanCredential.GetNetworkCredential().Password
.\scripts\run_web.ps1 `
  --lan --host $lanIp --port 2367 `
  --tls-cert 'C:\private\jawl-lan.crt' `
  --tls-key 'C:\private\jawl-lan.key' `
  --lan-public-host $lanIp
```

The launcher prints an HTTPS control URL. Open that URL from the tablet, for
example `https://192.168.1.23:2367/`. The browser's Basic-auth prompt uses
username `tablet` and the token as its password. Once the browser has accepted
the certificate and cached the origin credentials, the existing same-origin
UI bootstrap obtains its session/CSRF state without a new frontend login flow.

LAN support only changes bind, transport, and access checks. The command above
omits provider/worker options and therefore intentionally starts the default
`phase1_mock_brain` with optional audio services unconfigured. To use the same
live or local companion profile as on the PC, append the already validated
options to this command, for example `--jawl-web-url
http://127.0.0.1:8770`, `--voicemem-python`, `--asr-url` plus `--asr-model`,
and/or `--tts-url` plus its existing worker settings. `run_web.ps1` forwards
these arguments unchanged; it does not start JAWL or audio workers and does
not create credentials. Keep JAWL/provider tokens in their existing
environment variables.

For a machine with multiple interfaces, binding to the specific Wi-Fi/LAN IP
is preferable. `--host 0.0.0.0` is also supported in explicit LAN mode; add
`--lan-public-host 192.168.1.23` so the printed URL is useful. This feature
does not change Windows Firewall, UAC, router rules, or any protected upstream
runtime. Use it only on a trusted private network and stop the process when it
is not needed.

To use a different Basic-auth username, add `--lan-auth-user NAME`. To use the
default local mode again, omit `--lan`; no LAN token or certificate is needed:

```powershell
.\scripts\run_web.ps1
```

No physical tablet, certificate installation, or manual browser trust has been
claimed by the automated tests. The LAN tests cover opt-in bind validation,
TLS/token startup requirements, Basic-auth failures, session/CSRF enforcement,
and same-origin rejection.
