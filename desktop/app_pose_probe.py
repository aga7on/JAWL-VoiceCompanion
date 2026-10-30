"""Measure head-forward Z and arm geometry for the worn model."""

import itertools
import json
import urllib.request

import websocket

PROBE = """
(() => {
  const scene = window.__scene;
  const out = {};
  // find the vrm instance through the pivot
  let vrm = null;
  scene.traverse(o => { if (o.userData && o.userData.vrm) vrm = o.userData.vrm; });
  if (!vrm && window.__jawlScene) {
    // fallback: search internals via worn model check
  }
  out.facing = window.__jawlFacing;
  out.restPose = window.__jawlRestPose;
  out.pivotRotY = null;
  scene.traverse(o => { if (o.type === 'Group' && o.parent === scene) out.pivotRotY = o.rotation.y; });
  return JSON.stringify(out);
})()
"""


def main() -> int:
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read().decode())
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if "/app" in (t.get("url") or ""))
    ws = websocket.create_connection(ws_url, timeout=60)
    counter = itertools.count(1)

    def ev(expr, timeout=30):
        ws.settimeout(timeout)
        i = next(counter)
        ws.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
            "expression": expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == i:
                return message.get("result", {}).get("result", {}).get("value")

    print("probe:", ev(PROBE))
    # deeper: arm bone world positions via the scene internals
    deep = ev("""
    (() => {
      const THREE = null;
      // state.vrm is module-private; use the scene graph: find hips by name
      let report = {};
      const byName = {};
      window.__scene.traverse(o => { if (o.name) byName[o.name] = o; });
      report.boneNames = Object.keys(byName).filter(n => /Arm|Shoulder|Hips|Head/i.test(n)).slice(0, 14);
      const sh = byName['J_Bip_C_LeftShoulder'] || byName['leftShoulder'];
      const elbowL = byName['J_Bip_L_LowerArm'] || byName['leftLowerArm'];
      const upperL = byName['J_Bip_L_UpperArm'] || byName['leftUpperArm'];
      if (upperL && elbowL) {
        upperL.updateWorldMatrix(true, false);
        elbowL.updateWorldMatrix(true, false);
        const a = upperL.getWorldPosition(new (upperL.position.constructor)());
        const b = elbowL.getWorldPosition(new (elbowL.position.constructor)());
        report.leftArm = {shoulderY: +a.y.toFixed(3), elbowY: +b.y.toFixed(3), down: b.y < a.y};
      }
      const head = byName['J_Bip_C_Head'] || byName['head'];
      if (head) {
        head.updateWorldMatrix(true, false);
        report.headRotYWorld = null;
      }
      return JSON.stringify(report);
    })()
    """)
    print("deep:", deep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())