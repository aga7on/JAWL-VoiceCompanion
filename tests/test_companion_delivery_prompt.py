"""Prompt contract regression, not proof of model compliance."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'config/jawl/prompts/custom'


class CompanionDeliveryPromptTests(unittest.TestCase):
    def test_memory_key_guidance_matches_the_pinned_native_signature(self):
        source = ROOT.parents[3] / 'runtime/jawl-sources/jawl-20260906-daily-v2/src/l1_databases/sql/management/structured_memory.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        native = next(node for cls in tree.body if isinstance(cls, ast.ClassDef)
                      for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'remember')
        self.assertIn('memory_key', {argument.arg for argument in native.args.args})
        prompt = (ROOT / 'ZZ_MEMORY_WRITES.md').read_text(encoding='utf-8')
        self.assertIn('optional `memory_key` is valid', prompt)
        self.assertNotIn('rename fields such as `memory_key`', prompt)

    def test_direct_answer_does_not_instruct_empty_actions_before_delivery(self):
        prompt = (ROOT / 'RESPOND_DIRECTLY.md').read_text(encoding='utf-8')
        self.assertNotIn('отвечай сразу текстом и оставляй', prompt)
        self.assertIn('При наличии `_companion_turn_id`', prompt)
        self.assertIn('только ПОСЛЕ', prompt)
        self.assertIn('успешной доставки ответа этому turn', prompt)

    def test_background_silence_and_native_authority_are_preserved(self):
        prompt = (ROOT / 'RESPOND_DIRECTLY.md').read_text(encoding='utf-8')
        self.assertIn('молчание для фонового события', prompt)
        self.assertIn('Полномочия определяет JAWL policy', prompt)
        self.assertIn('Не публикуй внутренние thoughts', prompt)

    def test_duplicate_memory_recovery_is_bounded_and_not_fabricated(self):
        prompt = (ROOT / 'RESPOND_DIRECTLY.md').read_text(encoding='utf-8')
        for text in ('не повторяй его с теми же аргументами', 'один canonical lookup',
                     'SQLStructuredMemory.revise_memory', 'без успешного native результата'):
            self.assertIn(text, prompt)

    def test_delivery_override_still_requires_terminal_success(self):
        prompt = (ROOT / 'ZZ_COMPANION_DELIVERY.md').read_text(encoding='utf-8')
        self.assertIn('_companion_turn_id', prompt)
        self.assertIn('exactly one `HostTerminalMessages.send_message_to_terminal`', prompt)
        self.assertIn('after the tool\nreports success', prompt)
