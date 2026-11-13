# -*- coding: utf-8 -*-
"""Session supervisor: wait for DSH iteration boundary, print compact report. Exits on:
- DSH idle AND (STATE|TODO|CHANGELOG changed since baseline) -> prints report, exit 0
- DSH idle AND "This turn failed" after pivot grew -> prints failure report, exit 2
- timeout -> prints status, exit 3
Usage: python dsh_wait_report.py [--baseline-state MT] [--timeout 720]
"""
import json, os, re, sys, time, io, urllib.request, argparse
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
MCP = "http://127.0.0.1:5051"
PROJ = r"G:\AI\JAWL-VoiceCompanion-V0.5"
FILES = {"STATE": os.path.join(PROJ,"docs","STATE.md"),
         "TODO": os.path.join(PROJ,"TODO.md"),
         "CHANGELOG": os.path.join(PROJ,"CHANGELOG.md")}

def mcp(tab, cmd, args, wait=60):
    data = json.dumps({"tab": tab, "cmd": cmd, "args": args}).encode("utf-8")
    req = urllib.request.Request(f"{MCP}/job?wait={wait}", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=wait + 15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_err": str(e)}

def dom(sel, limit=2, chars=40):
    res = mcp("dsh","dom",{"sel":sel,"limit":limit,"textChars":chars})
    d = (res or {}).get("data") or {}
    return d.get("count") or 0, d.get("items") or []

def mtimes():
    o={}
    for k,p in FILES.items():
        try: o[k]=os.path.getmtime(p)
        except OSError: o[k]=0
    return o

def read_head(path, n=70):
    try:
        with open(path,"r",encoding="utf-8") as f: return "".join(f.readlines()[:n])
    except Exception as e: return f"(read err {e})"

def tail_fail_count():
    res = mcp("dsh","dom",{"sel":"body","limit":1,"textChars":500000}, wait=90)
    items = ((res or {}).get("data") or {}).get("items") or []
    n = re.sub(r"\s+"," ", items[0].get("text","") if items else "").strip()
    pivot = n.rfind("ПОЛНОДУПЛЕКСНЫЙ ГОЛОСОВОЙ СЛОЙ")
    seg = n[pivot:] if pivot>=0 else n[-12000:]
    fails = len(re.findall(r"This turn failed", seg))
    tail = seg[-900:]
    return fails, tail

ap = argparse.ArgumentParser()
ap.add_argument("--timeout", type=int, default=720)
ap.add_argument("--baseline-state", type=float, default=None)
args = ap.parse_args()
base = mtimes()
if args.baseline_state: base["STATE"] = args.baseline_state
base_fails, _ = tail_fail_count()
t0 = time.time()
while time.time()-t0 < args.timeout:
    time.sleep(25)
    stop,_ = dom('button[aria-label*="Stop"]',2,20)
    busy = stop>0
    mt = mtimes()
    changed = [k for k in mt if mt[k] != base.get(k,0)]
    fails, _ = tail_fail_count()
    if not busy and changed:
        print(f"=== COMPLETE changed={changed} busy={busy} fails_after={fails} ===")
        for k in ("STATE","TODO","CHANGELOG"):
            print(f"\n--- {k} head ---\n{read_head(FILES[k], 90)}")
        _, tail = tail_fail_count()
        print(f"\n--- DSH tail ---\n{tail}")
        sys.exit(0)
    if not busy and fails > base_fails and not changed:
        print(f"=== FAILED_IDLE fails {base_fails}->{fails} no_doc_change ===")
        _, tail = tail_fail_count()
        print(tail)
        sys.exit(2)
    if int(time.time()-t0) % 120 < 26:
        print(f"[wait] +{int(time.time()-t0)}s busy={busy} changed={changed} fails={fails}")
print(f"=== TIMEOUT {args.timeout}s ===")
mt = mtimes(); stop,_ = dom('button[aria-label*="Stop"]',2,20)
fails, tail = tail_fail_count()
print(f"busy={stop>0} changed={[k for k in mt if mt[k]!=base.get(k,0)]} fails={fails}")
print(tail)
sys.exit(3)
