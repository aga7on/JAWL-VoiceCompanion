"""Perception enrichment tests: background context reaches ordinary turns."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402
from jawl_voicecompanion.perception_packet import split_packet, render_packet


class _FakeFusion:
    def __init__(self, text: str) -> None:
        self.text = text

    def compose(self) -> str:
        return self.text


def _server(fusion):
    server = create_server(
        port=0,
        frontend_dir=ROOT / "frontend",
        gateway=TextGateway(),
        perception_fusion=fusion,
    )
    return server


class PerceptionEnrichmentTests(unittest.TestCase):
    def test_ordinary_turn_gets_background_perception(self):
        server = _server(_FakeFusion("\u042d\u043a\u0440\u0430\u043d: \u0430\u043d\u0438\u043c\u0435; \u0417\u0432\u0443\u043a: lo-fi, 92 BPM, A minor"))
        self.addCleanup(server.server_close)
        enriched = server.enrich_turn_text("\u041a\u0430\u043a \u0442\u0435\u0431\u0435 \u044d\u0442\u0430 \u0433\u0435\u0440\u043e\u0438\u043d\u044f \u0432 \u0436\u0451\u043b\u0442\u043e\u043c \u043f\u0430\u043b\u044c\u0442\u043e?")
        self.assertIn("<va_perception>", enriched)
        self.assertIn("\u0430\u043d\u0438\u043c\u0435", enriched)
        self.assertIn("lo-fi", enriched)

    def test_explicit_screen_question_keeps_strong_block(self):
        server = _server(_FakeFusion("\u042d\u043a\u0440\u0430\u043d: \u043e\u043a\u043d\u043e OpenCode \u0441 \u043b\u043e\u0433\u0430\u043c\u0438"))
        self.addCleanup(server.server_close)
        enriched = server.enrich_turn_text("\u0427\u0442\u043e \u0441\u0435\u0439\u0447\u0430\u0441 \u043d\u0430 \u044d\u043a\u0440\u0430\u043d\u0435?")
        utterance, packet = split_packet(enriched)
        self.assertEqual(utterance, "Что сейчас на экране?")
        self.assertIn("OpenCode", render_packet(packet))
        self.assertIn("OpenCode", enriched)

    def test_no_perception_leaves_turn_clean(self):
        server = _server(_FakeFusion(""))
        self.addCleanup(server.server_close)
        clean = "Напиши короткое письмо коллеге"
        self.assertEqual(server.enrich_turn_text(clean), clean)

    def test_no_fusion_leaves_turn_clean(self):
        server = _server(None)
        self.addCleanup(server.server_close)
        clean = "Что сейчас на экране?"
        self.assertEqual(server.enrich_turn_text(clean), clean)


if __name__ == "__main__":
    unittest.main()
