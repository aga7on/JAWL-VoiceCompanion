"""Synchronous VoiceMem ingest helper for the reflection job.

Run with the VoiceMem venv python (G:\\AI\\VoiceMem\\.venv\\Scripts\\python.exe).
Reads one JSON object from stdin:

    {"texts": ["..."], "user_id": "voice_user", "local": true}

and ingests each text through VoiceMem's own pipeline (local E5 classifier /
embedder, no external LLM). Prints one JSON result object on stdout.
"""

from __future__ import annotations

import json
import os
import sys

VOICEMEM_REPO = os.environ.get("VOICEMEM_REPO", r"G:\AI\VoiceMem")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    raw = sys.stdin.buffer.read()
    payload = json.loads(raw.decode("utf-8"))
    texts = [str(t)[:4000] for t in payload.get("texts", []) if str(t).strip()]
    if not texts:
        print(json.dumps({"ok": True, "ingested": 0}))
        return 0
    sys.path.insert(0, VOICEMEM_REPO)

    # Local-memory ingest still constructs VoiceMem's HTTP client; a machine
    # SOCKS proxy would break httpx without socksio. Keep loopback clean,
    # exactly like the sidecar does for local endpoints.
    base_url = os.environ.get("LLM_API_URL") or payload.get("base_url") or "http://127.0.0.1:8891/v1"
    from urllib.parse import urlsplit
    if urlsplit(base_url).hostname in {"127.0.0.1", "localhost", "::1"}:
        os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
        os.environ["no_proxy"] = os.environ["NO_PROXY"]
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(name, None)

    # VoiceMem's extraction/reply LLM model; the relay serves big-pickle.
    os.environ["OPENAI_MODEL"] = str(payload.get("model") or os.environ.get("OPENAI_MODEL") or "big-pickle")
    os.environ.setdefault("OPENAI_API_KEY", os.environ.get("LLM_API_KEY_1") or "local_dummy_key")

    from voicemem import VoiceMem

    overrides = {}
    if payload.get("local", True):
        from voicemem.leftbrain.cognitive_graph.local_query_classifier import LocalQueryClassifier
        from voicemem.leftbrain.local_e5_embedder import LocalE5Embedder

        overrides = {
            "schema": lambda: LocalQueryClassifier(),
            "embedding": lambda: LocalE5Embedder(),
        }
    vm = VoiceMem(
        mode=str(payload.get("mode", "normal")),
        memory_root=payload.get("memory_root"),
        user_id=str(payload.get("user_id", "voice_user")),
        base_url=base_url,
        api_key=os.environ.get("LLM_API_KEY_1") or "local_dummy_key",
        **overrides,
    )
    results = []
    for text in texts:
        try:
            vm.ingest(text=text)
            results.append({"ok": True})
        except Exception as exc:  # noqa: BLE001 - report per item, keep going
            results.append({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]})
    print(json.dumps({"ok": all(r["ok"] for r in results), "ingested": sum(1 for r in results if r["ok"]), "results": results}, ensure_ascii=False))
    return 0 if any(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
