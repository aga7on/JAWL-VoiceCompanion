"""Native CPU cancellation probe using a tiny generated graph, not Tera weights."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jawl_voicecompanion.onnx_cancellation import (  # noqa: E402
    CancellableSession, InferenceCancellation, InferenceCancelled, inference_scope,
)


def native_probe() -> dict:
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    import onnxruntime as ort

    scalar = lambda name, kind: helper.make_tensor_value_info(name, kind, [])
    body = helper.make_graph(
        [helper.make_node("Identity", ["continue_in"], ["continue_out"]),
         helper.make_node("Add", ["value_in", "one"], ["value_out"])],
        "bounded_fixture_body",
        [scalar("iteration", TensorProto.INT64), scalar("continue_in", TensorProto.BOOL),
         scalar("value_in", TensorProto.FLOAT)],
        [scalar("continue_out", TensorProto.BOOL), scalar("value_out", TensorProto.FLOAT)],
        [numpy_helper.from_array(np.array(1, np.float32), "one")],
    )
    graph = helper.make_graph(
        [helper.make_node("Loop", ["count", "condition", "value"], ["result"], body=body)],
        "cancel_fixture", [scalar("count", TensorProto.INT64), scalar("value", TensorProto.FLOAT)],
        [scalar("result", TensorProto.FLOAT)],
        [numpy_helper.from_array(np.array(True), "condition")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.log_severity_level = 4
    serialized = model.SerializeToString()
    session = ort.InferenceSession(serialized, sess_options=options, providers=["CPUExecutionProvider"])
    entered = {key: threading.Event() for key in ("a", "b")}
    observed = {}
    native_errors = {}
    results = {}

    class RecordingSession:
        def run(self, names, feeds, run_options):
            key = "a" if int(feeds["count"]) == 1_000_000_000 else "b"
            observed[key] = run_options
            entered[key].set()
            try:
                return session.run(names, feeds, run_options)
            except Exception as exc:
                native_errors[key] = f"{type(exc).__name__}: {exc}"[:500]
                raise

    proxy = CancellableSession(RecordingSession(), ort.RunOptions)
    tokens = {key: InferenceCancellation() for key in entered}

    def execute(key, count):
        try:
            with inference_scope(tokens[key]):
                results[key] = proxy.run(None, {"count": np.array(count, np.int64),
                                                 "value": np.array(0, np.float32)})
        except Exception as exc:
            results[key] = exc

    threads = [threading.Thread(target=execute, args=(key, count), daemon=True)
               for key, count in (("a", 1_000_000_000), ("b", 999_999_999))]
    try:
        for thread in threads:
            thread.start()
        if not all(event.wait(2) for event in entered.values()):
            raise AssertionError("native run did not enter")
        time.sleep(0.05)
        if not all(thread.is_alive() for thread in threads):
            raise AssertionError("fixture must still be inside native inference before cancel")
        started = time.perf_counter()
        tokens["a"].set()
        threads[0].join(1)
        cancel_ms = (time.perf_counter() - started) * 1000
        if threads[0].is_alive() or not isinstance(results.get("a"), InferenceCancelled):
            raise AssertionError("native cancellation did not release A within 1s")
        if "terminate" not in native_errors.get("a", "").lower():
            raise AssertionError("native termination status was not observed")
        time.sleep(0.02)
        if not threads[1].is_alive() or observed["b"].terminate:
            raise AssertionError("cancelling A affected B")
        tokens["b"].set()
        threads[1].join(1)
        if threads[1].is_alive() or not isinstance(results.get("b"), InferenceCancelled):
            raise AssertionError("B did not release after its own cancellation")
        with inference_scope(InferenceCancellation()):
            followup = CancellableSession(session, ort.RunOptions).run(
                None, {"count": np.array(16, np.int64), "value": np.array(0, np.float32)})
        if float(followup[0]) != 16:
            raise AssertionError("same-session follow-up failed")
        return {"status": "passed", "scope": "native_onnx_fixture_not_tera_weights",
                "onnxruntime": ort.__version__, "python": sys.version.split()[0],
                "providers": session.get_providers(), "graph_bytes": len(serialized),
                "cancel_a_ms": round(cancel_ms, 3), "a_cancel_did_not_stop_b": True,
                "same_session_followup": True, "native_termination_status_observed": True}
    finally:
        for token in tokens.values():
            token.set()
        for thread in threads:
            thread.join(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-native-onnx", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(native_probe()))
        return 0
    if not args.allow_native_onnx:
        parser.error("pass --allow-native-onnx for the tiny CPU fixture (no Tera weights)")
    try:
        child = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker"],
                               capture_output=True, text=True, timeout=15)
        if child.returncode:
            report = {"status": "failed", "scope": "native_onnx_fixture_not_tera_weights",
                      "child_exit": child.returncode, "error": child.stderr[-1500:]}
        else:
            report = json.loads(child.stdout)
    except subprocess.TimeoutExpired:
        report = {"status": "failed", "scope": "native_onnx_fixture_not_tera_weights",
                  "error": "owned native fixture child exceeded 15s and was reaped"}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
