import sys
import threading
import unittest

from jawl_voicecompanion.voicemem_client import VoiceMemAsyncIngest, VoiceMemProcessClient


class _FakeClient(VoiceMemProcessClient):
    def __init__(self):
        super().__init__(sys.executable, timeout_seconds=1)
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.aborted = False

    def feed_partial(self, text, *, ended=False, session_id="local"):
        self.calls.append((text, ended, session_id))
        self.started.set()
        self.release.wait(1)
        return []

    def abort(self):
        self.aborted = True
        self.release.set()


class VoiceMemAsyncIngestTests(unittest.TestCase):
    def test_queue_is_bounded_reports_drop_and_drains(self):
        client = _FakeClient()
        ingest = VoiceMemAsyncIngest(client, max_queue=1)
        try:
            self.assertEqual(ingest.enqueue_partial("one", session_id="s1")["status"], "queued")
            self.assertTrue(client.started.wait(1))
            self.assertEqual(ingest.enqueue_partial("two", session_id="s2")["status"], "queued")
            dropped = ingest.enqueue_partial("three", session_id="s3")
            self.assertEqual(dropped["status"], "dropped")
            self.assertEqual(dropped["reason"], "queue_full")
            client.release.set()
            self.assertTrue(ingest.wait_idle(2))
            state = ingest.state()
            self.assertEqual(state["accepted"], 2)
            self.assertEqual(state["completed"], 2)
            self.assertEqual(state["dropped"], 1)
            self.assertEqual([call[0] for call in client.calls], ["one", "two"])
        finally:
            ingest.close()

    def test_close_interrupts_a_slow_worker(self):
        client = _FakeClient()
        ingest = VoiceMemAsyncIngest(client, max_queue=1)
        self.assertEqual(ingest.enqueue_partial("slow")["status"], "queued")
        self.assertTrue(client.started.wait(1))
        ingest.close(timeout_seconds=0.1)
        self.assertTrue(client.aborted)
        self.assertEqual(ingest.state()["status"], "closed")


if __name__ == "__main__":
    unittest.main()
