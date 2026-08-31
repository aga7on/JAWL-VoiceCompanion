import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.browser_adapter import BrowserAdapter  # noqa: E402
from jawl_voicecompanion.hostos_policy import HostOSPolicy  # noqa: E402
from jawl_voicecompanion.hostos_tools import HostOSExecutor  # noqa: E402
from jawl_voicecompanion.models import AccessLevel, RiskClass, ToolRequest  # noqa: E402


class BrowserAdapterTests(unittest.TestCase):
    def test_url_open_is_bounded_and_redacts_query_in_result(self):
        opened = []

        def fake_open(url, **_kwargs):
            opened.append(url)
            return True

        adapter = BrowserAdapter(opener=fake_open)
        result = adapter.act("open_url", {"url": "https://example.test/path?token=secret#part"})
        self.assertEqual(result["status"], "verified")
        self.assertNotIn("secret", result["url"])
        self.assertEqual(opened, ["https://example.test/path?token=secret#part"])

    def test_browser_action_still_requires_hostos_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = HostOSPolicy(active_level=AccessLevel.OPERATOR)
            executor = HostOSExecutor(
                policy=policy,
                sandbox_root=Path(directory),
                browser=BrowserAdapter(opener=lambda *_args, **_kwargs: True),
                dry_run=True,
            )
            request = ToolRequest(
                tool="browser.act",
                risk=RiskClass.OBSERVE,
                arguments={"operation": "open_url", "url": "https://example.test"},
            )
            result = executor.execute(request)
            self.assertEqual(result["status"], "approval_required")

    def test_invalid_scheme_is_rejected(self):
        result = BrowserAdapter(opener=lambda *_args, **_kwargs: True).act(
            "open_url", {"url": "file:///secret.txt"}
        )
        self.assertEqual(result["status"], "denied")


if __name__ == "__main__":
    unittest.main()

