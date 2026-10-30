"""Native adapter using real loopback sockets, never an agent/model/device."""
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from jawl_voicecompanion.jawl_adapter import JawlTurnCancelled
from jawl_voicecompanion.jawl_web import JawlWebChatAdapter, JawlWebUnavailable


def _final(turn_id):
    return {'schema_version': 1, 'response_id': f'resp-{turn_id}', 'turn_id': turn_id,
            'text': 'Готово', 'speak': True,
            'emotion': {'id': 'attentive', 'intensity': .45, 'confidence': .8},
            'avatar': {'expression': 'attentive', 'motion': 'soft_nod', 'state': 'speaking'},
            'voice': {'provider': 'jawl', 'voice_id': 'main_ru', 'rate': 1.0},
            'actions': [], 'interruptible': True, 'proactive': False}


class _NativePeer:
    def __init__(self, *, trickle_turn=False, trickle_cancel=False):
        self.stop = threading.Event()
        self.turn_seen, self.turn_eof = threading.Event(), threading.Event()
        self.calls, self.streams = [], []
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                queue = Queue()
                with owner.lock:
                    owner.streams.append(queue)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                try:
                    self.wfile.write(b'data: {}\n\n')
                    self.wfile.flush()
                    while not owner.stop.is_set():
                        try:
                            packet = queue.get(timeout=.05)
                        except Empty:
                            continue
                        self.wfile.write(b'data: ' + json.dumps(packet).encode() + b'\n\n')
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    with owner.lock:
                        owner.streams.remove(queue)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                turn_id = payload['turn_id']
                with owner.lock:
                    owner.calls.append((self.path, turn_id))
                if self.path.endswith('/turn'):
                    owner.turn_seen.set()
                    if turn_id == 'blocked-A':
                        self.connection.settimeout(1.5)
                        try:
                            if self.connection.recv(1) == b'':
                                owner.turn_eof.set()
                        except OSError:
                            pass
                        return
                    if turn_id == 'followup-B':
                        owner.stop.wait(.6)  # Spans A's original deadline.
                    trickle = trickle_turn
                else:
                    trickle = trickle_cancel
                body = json.dumps({'ok': True, 'turn_id': turn_id}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    if trickle:
                        for value in body:
                            self.wfile.write(bytes([value]))
                            self.wfile.flush()
                            if owner.stop.wait(.05):
                                return
                    else:
                        self.wfile.write(body)
                        self.wfile.flush()
                    if self.path.endswith('/turn'):
                        event = {'schema_version': 1, 'event_seq': 1, 'turn_id': turn_id,
                                 'type': 'assistant.final', 'payload': {'response': _final(turn_id)}}
                        with owner.lock:
                            for queue in owner.streams:
                                queue.put({'events': [event]})
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.02), daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def adapter(self, timeout=.5):
        return JawlWebChatAdapter(f'http://127.0.0.1:{self.server.server_port}',
                                  token='fixture-native-token', timeout_seconds=timeout,
                                  chat_timeout_seconds=3, native_gateway=True)


class NativePostLifecycleTests(unittest.TestCase):
    def _peer(self, **kwargs):
        peer = _NativePeer(**kwargs)
        self.addCleanup(peer.close)
        return peer

    @staticmethod
    def _run(adapter, cancel, result):
        try:
            result.put(adapter.respond('Привет', cancel_event=cancel, correlation_id='blocked-A'))
        except Exception as exc:
            result.put(exc)

    def test_preheader_stop_aborts_post_sends_exact_cancel_and_allows_followup(self):
        peer = self._peer()
        adapter = peer.adapter()
        cancel, result = threading.Event(), Queue()
        thread = threading.Thread(target=self._run, args=(adapter, cancel, result), daemon=True)
        thread.start()
        self.assertTrue(peer.turn_seen.wait(1))
        started = time.monotonic()
        cancel.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(result.get(timeout=.2), JawlTurnCancelled)
        self.assertTrue(peer.turn_eof.wait(.5), 'server did not observe socket EOF')
        self.assertLess(time.monotonic() - started, 1)
        adapter.timeout_seconds = 1.2
        self.assertEqual(adapter.respond('Далее', correlation_id='followup-B'), 'Готово')
        self.assertEqual(peer.calls, [('/api/companion/turn', 'blocked-A'),
                                     ('/api/companion/cancel', 'blocked-A'),
                                     ('/api/companion/turn', 'followup-B')])
        self.assertFalse(adapter._native_turn_lock.locked())
        self.assertFalse(any(t.name == 'jawl-http-deadline' and t.is_alive()
                             for t in threading.enumerate()))

    def test_trickled_turn_ack_times_out_without_mutation_replay(self):
        peer = self._peer(trickle_turn=True)
        adapter = peer.adapter(timeout=.2)
        started = time.monotonic()
        with self.assertRaises(JawlWebUnavailable):
            adapter.respond('Привет', correlation_id='trickled-turn')
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(peer.calls, [('/api/companion/turn', 'trickled-turn'),
                                     ('/api/companion/cancel', 'trickled-turn')])
        self.assertFalse(adapter._native_turn_lock.locked())

    def test_cancel_has_independent_absolute_deadline(self):
        peer = self._peer(trickle_cancel=True)
        adapter = peer.adapter(timeout=.2)
        started = time.monotonic()
        self.assertFalse(adapter._post_native_cancel('cancel-id'))
        self.assertLess(time.monotonic() - started, .9)
        self.assertEqual(peer.calls, [('/api/companion/cancel', 'cancel-id')])


if __name__ == '__main__':
    unittest.main()
