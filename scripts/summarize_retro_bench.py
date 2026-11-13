import json
from pathlib import Path

p = Path("runtime/instances/retro_bench/benchmark_results.json")
data = json.loads(p.read_text(encoding="utf-8"))

print("| Strategy | Budget K | Hit Rate | 100ms | 150ms | 250ms | 500ms | T-Motion | T-Static | O-Static | O-Flash | Latency p50 | Unreadable Acc |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in data["runs"]:
    s = r["strategy"]
    b = r["budget"]
    hr = f"{r['frame_hit_rate']*100:.1f}%"
    d100 = f"{r['hit_rate_by_duration']['100']*100:.1f}%"
    d150 = f"{r['hit_rate_by_duration']['150']*100:.1f}%"
    d250 = f"{r['hit_rate_by_duration']['250']*100:.1f}%"
    d500 = f"{r['hit_rate_by_duration']['500']*100:.1f}%"
    tm = f"{r['hit_rate_by_class']['T-Motion']*100:.1f}%"
    ts = f"{r['hit_rate_by_class']['T-Static']*100:.1f}%"
    os_ = f"{r['hit_rate_by_class']['O-Static']*100:.1f}%"
    of = f"{r['hit_rate_by_class']['O-Flash']*100:.1f}%"
    lat = f"{r['latency_ms']['total_p50']:.1f} ms"
    unr = f"{r['unreadable_control_accuracy']*100:.1f}%"
    print(f"| {s:16s} | {b:2d} | {hr:8s} | {d100:6s} | {d150:6s} | {d250:6s} | {d500:6s} | {tm:8s} | {ts:8s} | {os_:8s} | {of:8s} | {lat:11s} | {unr:14s} |")
