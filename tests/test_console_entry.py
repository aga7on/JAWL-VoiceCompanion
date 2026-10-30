import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("owned_console_entry_test", Path(__file__).parents[1] / "scripts/run_owned_jawl_console.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConsoleEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_browser_entry_uses_companion_session_without_exposing_token(self):
        from aiohttp import web
        app = SimpleNamespace(middlewares=[])
        with patch.dict(os.environ, {"JAWL_COMPANION_UI_URL": "http://127.0.0.1:2367"}):
            module.install_companion_console_entry(app, "private-test-token")
        request = SimpleNamespace(method="GET", path="/", headers={}, query={})
        async def handler(req):
            return "native page"
        with self.assertRaises(web.HTTPFound) as caught:
            await app.middlewares[0](request, handler)
        self.assertEqual(caught.exception.location, "http://127.0.0.1:2367/app?openConsole=1")
        self.assertNotIn("private-test-token", caught.exception.location)

    async def test_authorized_proxy_request_keeps_native_page(self):
        app = SimpleNamespace(middlewares=[])
        with patch.dict(os.environ, {"JAWL_COMPANION_UI_URL": "http://127.0.0.1:2367"}):
            module.install_companion_console_entry(app, "fixture")
        request = SimpleNamespace(method="GET", path="/", headers={"X-Console-Token": "fixture"}, query={})
        async def handler(req):
            return "native page"
        self.assertEqual(await app.middlewares[0](request, handler), "native page")

    async def test_nonlocal_redirect_is_never_installed(self):
        app = SimpleNamespace(middlewares=[])
        with patch.dict(os.environ, {"JAWL_COMPANION_UI_URL": "https://outside.example"}):
            module.install_companion_console_entry(app, "fixture")
        self.assertEqual(app.middlewares, [])
