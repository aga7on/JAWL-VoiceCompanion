from dataclasses import dataclass
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from jawl_voicecompanion.onnx_cancellation import (
    CancellableSession, InferenceCancellation, InferenceCancelled, inference_scope, wrap_loaded_tts,
)


class FakeOptions:
    terminate = False


class FakeSession:
    def __init__(self):
        self.options = []

    def run(self, output_names, input_feed, run_options=None):
        self.options.append(run_options)
        return [input_feed]

    def get_inputs(self):
        return ["input"]


@dataclass(frozen=True)
class Loaded:
    text_encoder: object
    duration_predictor: object
    sampler: object
    vocoder: object
    accentizer: object = None


class ONNXCancellationTests(unittest.TestCase):
    def test_pre_cancel_skips_native_run(self):
        session = FakeSession()
        proxy = CancellableSession(session, FakeOptions)
        token = InferenceCancellation()
        token.set()
        with self.assertRaises(InferenceCancelled), inference_scope(token):
            proxy.run(None, {})
        self.assertEqual(session.options, [])

    def test_each_run_gets_distinct_options_and_finished_run_is_detached(self):
        session = FakeSession()
        proxy = CancellableSession(session, FakeOptions)
        token = InferenceCancellation()
        with inference_scope(token):
            self.assertEqual(proxy.run(None, {"a": 1}), [{"a": 1}])
            proxy.run(None, {})
        token.set()
        self.assertIsNot(session.options[0], session.options[1])
        self.assertTrue(all(not options.terminate for options in session.options))
        self.assertEqual(token._runs, {})
        self.assertEqual(proxy.get_inputs(), ["input"])

    def test_cancel_a_does_not_terminate_b_using_the_same_native_session(self):
        entered = {name: threading.Event() for name in ("a", "b")}
        release = threading.Event()
        observed = {}
        results = {}

        class Native:
            def run(self, names, feeds, options):
                key = feeds["key"]
                observed[key] = options
                entered[key].set()
                while not release.wait(0.01):
                    if options.terminate:
                        raise RuntimeError("native terminated")
                return [key]

        proxy = CancellableSession(Native(), FakeOptions)
        tokens = {name: InferenceCancellation() for name in entered}
        def run(key):
            try:
                with inference_scope(tokens[key]):
                    results[key] = proxy.run(None, {"key": key})
            except Exception as exc:
                results[key] = exc
        threads = [threading.Thread(target=run, args=(name,), daemon=True) for name in entered]
        try:
            for thread in threads:
                thread.start()
            self.assertTrue(all(event.wait(1) for event in entered.values()))
            tokens["a"].set()
            threads[0].join(1)
            self.assertFalse(threads[0].is_alive())
            self.assertIsInstance(results["a"], InferenceCancelled)
            self.assertTrue(observed["a"].terminate)
            self.assertFalse(observed["b"].terminate)
            release.set()
            threads[1].join(1)
            self.assertEqual(results["b"], ["b"])
        finally:
            release.set()
            for thread in threads:
                thread.join(2)
                self.assertFalse(thread.is_alive())

    def test_unrelated_native_error_is_not_disguised_as_cancel(self):
        class Broken:
            def run(self, *_args):
                raise ValueError("native failure")
        with inference_scope(InferenceCancellation()):
            with self.assertRaisesRegex(ValueError, "native failure"):
                CancellableSession(Broken(), FakeOptions).run(None, {})

    def test_context_is_restored_after_failure(self):
        session = FakeSession()
        proxy = CancellableSession(session, FakeOptions)
        with self.assertRaises(ValueError):
            with inference_scope(InferenceCancellation()):
                raise ValueError("leave scope")
        proxy.run(None, {})
        self.assertIsNone(session.options[-1])

    def test_wrap_copies_owners_and_covers_all_eight_sessions(self):
        session = FakeSession()
        accent = SimpleNamespace(mode="full", dictionary={"word": "value"})
        for name in ("accent_model", "omograph_model", "stress_usage", "yo_classifier"):
            setattr(accent, name, SimpleNamespace(session=session))
        original = Loaded(session, session, session, session, accent)
        wrapped = wrap_loaded_tts(original, FakeOptions)
        self.assertIsNot(original, wrapped)
        self.assertIs(original.text_encoder, session)
        self.assertIsNot(original.accentizer, wrapped.accentizer)
        self.assertIs(original.accentizer.dictionary, wrapped.accentizer.dictionary)
        with inference_scope(InferenceCancellation()):
            for name in ("text_encoder", "duration_predictor", "sampler", "vocoder"):
                getattr(wrapped, name).run(None, {})
            for name in ("accent_model", "omograph_model", "stress_usage", "yo_classifier"):
                self.assertIs(getattr(original.accentizer, name).session, session)
                getattr(wrapped.accentizer, name).session.run(None, {})
        self.assertEqual(len(session.options), 8)
        self.assertEqual(len({id(options) for options in session.options}), 8)

    def test_dictionary_and_none_accent_modes_preserve_their_selection(self):
        session = FakeSession()
        for accent in (None, SimpleNamespace(mode="dictionary")):
            wrapped = wrap_loaded_tts(Loaded(session, session, session, session, accent), FakeOptions)
            if accent is None:
                self.assertIsNone(wrapped.accentizer)
            else:
                self.assertEqual(wrapped.accentizer.mode, "dictionary")

    def test_unknown_layout_or_unowned_run_options_fail_closed(self):
        session = FakeSession()
        with self.assertRaises(ValueError):
            wrap_loaded_tts(Loaded(session, session, session, session, SimpleNamespace(mode="unknown")), FakeOptions)
        with self.assertRaises(AttributeError):
            CancellableSession(session, FakeOptions).run_async
        with inference_scope(InferenceCancellation()):
            with self.assertRaises(ValueError):
                CancellableSession(session, FakeOptions).run(None, {}, FakeOptions())


if __name__ == "__main__":
    unittest.main()
