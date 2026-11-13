#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browser_mcp.py — прямой командный канал в открытые вкладки Firefox через Tampermonkey.

Схема: локальный клиент (агент) кладёт задание POST /job, userscript-воркер
(bridge-console.user.js) в вкладке забирает его GET /jobs?tab=..., исполняет в
контексте страницы и отдаёт POST /job_result. Клиент получает результат синхронно.

Порт 5051 (5050 занят фазовым мостом connect_seniors.py). Привязка 127.0.0.1 —
выполнять команды может любой локальный процесс, это осознанное решение для своего ПК.

HTTP:
  GET  /health                  → {"tabs": {tab: {"alive","last_seen","queued"}}}
  GET  /jobs?tab=chatgpt        → {"id","cmd","args"} | {"cmd": null}   (пульс воркера)
  GET  /job/<id>                → результат задания
  POST /job  {"tab","cmd","args"} (&wait=сек, по умолчанию 30) → синхронный результат
  POST /job_result {"id","ok","data","error"} → ответ воркера

CLI:  python browser_mcp.py call <tab> <cmd> [JSON-args]
Коды выхода CLI: 0 результат получен; 2 таймаут воркера.
"""
import json
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT = 5051
HOST = "127.0.0.1"
ALIVE_WINDOW = 15.0  # сек: воркер считается живым, если недавно опрашивал

LOCK = threading.Lock()
JOBS = {}        # id -> job
QUEUES = {}      # tab -> [job_id]
LAST_SEEN = {}   # tab -> ts


def enqueue(tab, cmd, args):
    job = {"id": uuid.uuid4().hex[:12], "tab": tab, "cmd": cmd,
           "args": args if isinstance(args, dict) else {}, "status": "pending", "result": None}
    with LOCK:
        JOBS[job["id"]] = job
        QUEUES.setdefault(tab, []).append(job["id"])
    return job


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        try:
            print(f"[http] {fmt % args}")
        except Exception:
            pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self):
        q = urlparse(self.path)
        params = parse_qs(q.query)
        job = None
        if q.path == "/health":
            now = time.time()
            with LOCK:
                tabs = {t: {"alive": now - ts < ALIVE_WINDOW, "last_seen": round(ts, 1),
                            "queued": len(QUEUES.get(t, []))} for t, ts in LAST_SEEN.items()}
            self._json({"tabs": tabs})
            return
        if q.path == "/jobs":
            tab = params.get("tab", [""])[0].strip()
            with LOCK:
                LAST_SEEN[tab] = time.time()
                queue = QUEUES.get(tab, [])
                if queue:
                    job = JOBS.get(queue.pop(0))
            self._json({"id": job["id"], "cmd": job["cmd"], "args": job["args"]}
                       if job else {"cmd": None})
            return
        if q.path.startswith("/job/"):
            job_id = q.path.split("/job/", 1)[1].strip()
            with LOCK:
                job = JOBS.get(job_id)
            self._json(job["result"] if job and job["result"] is not None
                       else {"status": "pending"})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        q = urlparse(self.path)
        params = parse_qs(q.query)
        try:
            body = self._body()
        except Exception:
            self._json({"error": "bad json"}, 400)
            return
        if q.path == "/job":
            tab = (body.get("tab") or "").strip()
            cmd = (body.get("cmd") or "").strip()
            if not tab or not cmd:
                self._json({"error": "tab и cmd обязательны"}, 400)
                return
            job = enqueue(tab, cmd, body.get("args"))
            wait = float(params.get("wait", ["30"])[0])
            t0 = time.time()
            while time.time() - t0 < wait:
                with LOCK:
                    done = job["result"] is not None
                if done:
                    break
                time.sleep(0.15)
            with LOCK:
                res = job["result"]
            self._json(res if res else {"status": "timeout", "id": job["id"],
                                        "note": "воркер вкладки не ответил"})
            return
        if q.path == "/job_result":
            job_id = (body.get("id") or "").strip()
            with LOCK:
                job = JOBS.get(job_id)
                if job:
                    job["result"] = {"id": job_id, "ok": bool(body.get("ok")),
                                     "data": body.get("data"), "error": body.get("error")}
            self._json({"status": "ok" if job else "unknown_id"})
            return
        self._json({"error": "not found"}, 404)


def cli_call(tab, cmd, args):
    data = json.dumps({"tab": tab, "cmd": cmd, "args": args}).encode("utf-8")
    req = urllib.request.Request(f"http://{HOST}:{PORT}/job?wait=25", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode("utf-8"))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("status") == "timeout":
        sys.exit(2)


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "call":
        args = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
        cli_call(sys.argv[2], sys.argv[3], args)
        return
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"[mcp] порт {PORT} занят ({exc}) — возможно, сервер уже работает")
        sys.exit(1)
    print(f"[mcp] сервер команд на http://{HOST}:{PORT}; жду воркеры "
          f"(chatgpt/arena/dsh); CLI: python browser_mcp.py call <tab> ping")
    server.serve_forever()


if __name__ == "__main__":
    main()
