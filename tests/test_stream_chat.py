import threading
import time
import unittest

from jawl_voicecompanion.stream_chat import StreamChatIngestor, StreamChatLimits


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class StreamChatIngestorTests(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "ingestor", None) is not None:
            self.ingestor.close()

    def test_normalizes_allowlists_and_delivers_safe_envelope(self):
        received = []
        delivered = threading.Event()

        def sink(event):
            received.append(event)
            delivered.set()

        self.ingestor = StreamChatIngestor(sink, session_id="session-1")
        result = self.ingestor.accept(
            {
                "id": "message-7",
                "platform": " Twitch ",
                "author": "  Артём\n",
                "channel_id": "channel",
                "text": "  Привет\x00,   компаньон! ",
                "ignored": "must not cross boundary",
            },
            {"url": "HTTPS://Example.COM/watch?v=secret&token=bad#fragment", "title": "  Stream\n"},
        )
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(delivered.wait(1.0))
        self.assertEqual(len(received), 1)
        event = received[0]
        self.assertEqual(event["source"], "stream_chat")
        self.assertEqual(event["type"], "CHAT_MESSAGE")
        self.assertEqual(event["session_id"], "session-1")
        self.assertEqual(event["payload"]["text"], "Привет, компаньон!")
        self.assertNotIn("ignored", event)
        self.assertNotIn("ignored", event["payload"])
        self.assertEqual(event["payload"]["url_metadata"]["url"], "https://example.com/watch")
        self.assertEqual(event["payload"]["url_metadata"]["host"], "example.com")

    def test_accepts_nested_provider_payload_and_deduplicates_id(self):
        received = []
        delivered = threading.Event()

        def sink(event):
            received.append(event)
            delivered.set()

        self.ingestor = StreamChatIngestor(sink)
        event = {"id": "same", "payload": {"text": "hello", "user": "viewer"}, "platform": "youtube"}
        self.assertEqual(self.ingestor.accept(event)["status"], "accepted")
        self.assertEqual(self.ingestor.accept(event)["status"], "duplicate")
        self.assertTrue(delivered.wait(1.0))
        self.assertEqual(len(received), 1)
        self.assertEqual(self.ingestor.state()["stats"]["duplicates"], 1)

    def test_text_without_id_is_deduplicated_and_fields_are_bounded(self):
        received = []
        delivered = threading.Event()
        limits = StreamChatLimits(max_text=8, max_author=5, max_queue_items=4, rate_burst=4)

        def sink(event):
            received.append(event)
            delivered.set()

        self.ingestor = StreamChatIngestor(sink, limits=limits)
        event = {"author": "viewer-name", "text": "  one   two   three  "}
        self.assertEqual(self.ingestor.accept(event)["status"], "accepted")
        self.assertEqual(self.ingestor.accept(event)["status"], "duplicate")
        self.assertTrue(delivered.wait(1.0))
        self.assertEqual(received[0]["payload"]["text"], "one two ")
        self.assertEqual(received[0]["payload"]["author"], "viewe")

    def test_moderation_is_fail_closed_and_runs_on_safe_envelope(self):
        inspected = []

        def moderate(event):
            inspected.append(event)
            return event["payload"]["text"] != "blocked"

        self.ingestor = StreamChatIngestor(moderation_hook=moderate)
        self.assertEqual(self.ingestor.accept({"text": "blocked", "secret": "x"})["status"], "moderated")
        self.assertEqual(self.ingestor.accept({"text": "allowed"})["status"], "accepted")
        self.assertNotIn("secret", inspected[0])
        self.assertNotIn("secret", inspected[0]["payload"])

        failed = StreamChatIngestor(moderation_hook=lambda _: 1 / 0)
        try:
            self.assertEqual(failed.accept({"text": "fail closed"})["status"], "moderated")
        finally:
            failed.close()

    def test_rate_limit_and_backpressure_are_nonblocking(self):
        clock = FakeClock()
        gate = threading.Event()
        limits = StreamChatLimits(rate_per_second=1.0, rate_burst=1, max_queue_items=1, max_queue_bytes=10000)
        self.ingestor = StreamChatIngestor(lambda _: gate.wait(1), limits=limits, clock=clock)
        self.assertEqual(self.ingestor.accept({"id": "1", "text": "first"})["status"], "accepted")
        self.assertEqual(self.ingestor.accept({"id": "2", "text": "second"})["status"], "rate_limited")
        clock.advance(1.0)
        self.assertEqual(self.ingestor.accept({"id": "3", "text": "third"})["status"], "backpressure")
        gate.set()
        time.sleep(0.05)
        clock.advance(1.0)
        self.assertEqual(self.ingestor.accept({"id": "4", "text": "fourth"})["status"], "accepted")

    def test_stop_drain_false_drops_queue_and_close_is_terminal(self):
        gate = threading.Event()
        limits = StreamChatLimits(rate_burst=4, max_queue_items=4)
        self.ingestor = StreamChatIngestor(lambda _: gate.wait(1), limits=limits)
        self.assertEqual(self.ingestor.accept({"id": "1", "text": "held"})["status"], "accepted")
        self.assertEqual(self.ingestor.accept({"id": "2", "text": "dropped"})["status"], "accepted")
        state = self.ingestor.stop(drain=False)
        gate.set()
        self.assertEqual(state["state"], "stopped")
        self.assertEqual(state["queued_items"], 0)
        self.assertGreaterEqual(state["stats"]["dropped_on_stop"], 1)
        self.assertEqual(self.ingestor.close()["state"], "closed")
        self.assertEqual(self.ingestor.accept({"text": "after close"})["status"], "stopped")

    def test_stop_drain_true_delivers_pending_events(self):
        received = []
        self.ingestor = StreamChatIngestor(received.append)
        self.ingestor.accept({"id": "1", "text": "one"})
        self.ingestor.accept({"id": "2", "text": "two"})
        state = self.ingestor.stop(drain=True, timeout=1.0)
        self.assertEqual(state["state"], "stopped")
        self.assertEqual([event["payload"]["text"] for event in received], ["one", "two"])

    def test_invalid_url_and_empty_text_are_rejected_without_network(self):
        self.ingestor = StreamChatIngestor()
        self.assertEqual(self.ingestor.accept({"text": "ok"}, {"url": "file:///secret"})["status"], "invalid")
        self.assertEqual(self.ingestor.accept({"text": "   "})["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
