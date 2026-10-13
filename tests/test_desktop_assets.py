"""The scene's local ES-module dependencies must actually be served."""
import sys
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jawl_voicecompanion.web import create_server


class DesktopAssetsTests(unittest.TestCase):
    def test_motion_dependency_is_javascript_not_frontend_fallback(self):
        server = create_server('127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for asset, exported in [
                ('avatar-motion.js', b'export function createAvatarMotionController'),
                ('avatar-physics.js', b'export function createAvatarPhysicsController'),
                ('speech-stream.js', b'export '),
                ('voice-input.js', b'export class MicInputGate'),
                ('voice-draft.js', b'export function createVoiceDraftController'),
            ]:
                with self.subTest(asset=asset), urlopen(f'http://127.0.0.1:{server.server_port}/{asset}', timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn('javascript', response.headers['Content-Type'])
                    self.assertIn(exported, response.read())
            for path in ['/app/runtime/private.json', '/app/node_modules/../../config/runtime.manifest.json']:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(f'http://127.0.0.1:{server.server_port}{path}', timeout=5)
                self.assertEqual(caught.exception.code, 404)
                caught.exception.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == '__main__':
    unittest.main()
