import http.cookiejar
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

report = {
    "timestamp": time.time(),
    "checks": {}
}

# 1. Gateway Session & Live Turn
try:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open("http://127.0.0.1:2367/api/session", timeout=5) as r:
        session_data = json.loads(r.read())
        csrf = session_data["csrf_token"]
    
    headers = {
        "X-Companion-CSRF": csrf,
        "Origin": "http://127.0.0.1:2367",
        "Host": "127.0.0.1:2367",
        "Content-Type": "application/json",
    }
    query = "Как настроение? Всё готово к полноценной работе?"
    payload = json.dumps({"text": query}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:2367/api/chat", data=payload, headers=headers)
    t0 = time.perf_counter()
    with opener.open(req, timeout=60) as r:
        chat_resp = json.loads(r.read())
        chat_elapsed = time.perf_counter() - t0

    resp_text = chat_resp.get("text", "")
    has_hanzi = any("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" for ch in resp_text)
    
    report["checks"]["live_chat"] = {
        "ok": bool(resp_text) and not has_hanzi,
        "elapsed_seconds": round(chat_elapsed, 2),
        "text": resp_text,
        "has_hanzi": has_hanzi,
        "emotion": chat_resp.get("emotion"),
        "avatar": chat_resp.get("avatar"),
    }
except Exception as exc:
    report["checks"]["live_chat"] = {"ok": False, "error": str(exc)}

# 2. OmniVoice TTS Synthesis for the reply
try:
    text_to_speak = report["checks"]["live_chat"].get("text", "Система активна и готова к работе.")
    tts_payload = json.dumps({"text": text_to_speak}, ensure_ascii=False).encode("utf-8")
    tts_req = urllib.request.Request("http://127.0.0.1:9890/tts", data=tts_payload, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(tts_req, timeout=30) as r:
        wav_data = r.read()
        tts_elapsed = time.perf_counter() - t0
        is_wav = wav_data[:4] == b"RIFF" and wav_data[8:12] == b"WAVE"
    report["checks"]["omnivoice_tts"] = {
        "ok": is_wav and len(wav_data) > 1000,
        "elapsed_seconds": round(tts_elapsed, 2),
        "bytes": len(wav_data),
        "is_valid_wav": is_wav,
    }
except Exception as exc:
    report["checks"]["omnivoice_tts"] = {"ok": False, "error": str(exc)}

# 3. Sensory perception freshness
try:
    perception_file = r"G:\AI\JAWL-VoiceCompanion-V0.5\runtime\instances\daily\data\sensory\current-perception.json"
    if os.path.exists(perception_file):
        mtime = os.path.getmtime(perception_file)
        age = time.time() - mtime
        with open(perception_file, "r", encoding="utf-8") as f:
            pdata = json.load(f)
        report["checks"]["sensory_perception"] = {
            "ok": age < 30.0,
            "age_seconds": round(age, 1),
            "channels": list(pdata.get("channels", {}).keys()),
        }
    else:
        report["checks"]["sensory_perception"] = {"ok": False, "error": "file not found"}
except Exception as exc:
    report["checks"]["sensory_perception"] = {"ok": False, "error": str(exc)}

# Summary
all_ok = all(c.get("ok", False) for c in report["checks"].values())
report["all_ok"] = all_ok

print(json.dumps(report, indent=2, ensure_ascii=False))
