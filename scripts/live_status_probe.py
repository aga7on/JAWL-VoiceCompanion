import urllib.request
import http.cookiejar
import json

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

with opener.open("http://127.0.0.1:2367/api/session") as r:
    data = json.loads(r.read())
    csrf = data["csrf_token"]

def make_req(path, data=None):
    headers = {
        "X-Companion-CSRF": csrf,
        "Origin": "http://127.0.0.1:2367",
        "Host": "127.0.0.1:2367",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(data).encode("utf-8")
        return urllib.request.Request(f"http://127.0.0.1:2367{path}", data=payload, headers=headers)
    return urllib.request.Request(f"http://127.0.0.1:2367{path}", headers=headers)

with opener.open(make_req("/api/doctor")) as r:
    doc = json.loads(r.read())
    print("=== LIVE DOCTOR STATUS ===")
    print("Doctor overall status:", doc.get("status"))
    for c in doc.get("checks", []):
        print(f" - {c['id']}: ready={c.get('ready')} | status={c.get('status')} | {c.get('details')}")

with opener.open(make_req("/api/state")) as r:
    state = json.loads(r.read())
    print("\n=== LIVE COMPANION STATE ===")
    print("Avatar audio speaking:", state.get("avatar_audio", {}).get("speaking"))
    print("Active profile:", state.get("active_profile"))
    print("Last turn:", state.get("last_turn"))
    print("Voice config:", state.get("voice"))
    print("HostOS level:", state.get("hostos", {}).get("level"))

with opener.open(make_req("/api/audio/router")) as r:
    router = json.loads(r.read())
    print("\n=== AUDIO ROUTER ===")
    print("Router mode:", router.get("mode"))
    print("Self PID:", router.get("self_pid"))
    print("Exclude PIDs count:", len(router.get("exclude_pids", [])))

with opener.open(make_req("/api/audio/sessions")) as r:
    sessions = json.loads(r.read())
    print("\n=== WASAPI AUDIO SESSIONS ===")
    print(f"Total active audio sessions: {len(sessions.get('sessions', []))}")
    for s in sessions.get("sessions", [])[:5]:
        print(f" - [{s.get('process_name')}] (PID {s.get('pid')}): peak={s.get('peak')}, category={s.get('category')}, title={s.get('window_title')}")
