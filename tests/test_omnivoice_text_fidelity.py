"""Guard the TTS worker's text fidelity contract.

Regression context: the OmniVoice worker used reference-based voice cloning,
and on this model build every reference-based mode injected the reference
sentence into the answer. GigaAM transcribed a request for "Какой сегодня
статус моего проекта?" as the reference phrase ("Привет! Я твой голосовой
компаньон...") — an unusable voice lane for real answers.

These tests pin the decision instead of the model: the worker must not pass a
reference sample into generation, because answer text outranks voice similarity.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "omnivoice_server.py"


def _server_tree() -> ast.Module:
    return ast.parse(SERVER.read_text(encoding="utf-8"))


def _synthesize_node(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "synthesize":
            return node
    raise AssertionError("synthesize() is missing from the TTS worker")


def test_synthesize_does_not_inject_reference_sample() -> None:
    """No ref_audio/ref_text may reach model.generate(): they corrupt answers."""
    node = _synthesize_node(_server_tree())
    offending: list[str] = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "generate":
            continue
        for keyword in call.keywords:
            if keyword.arg in {"ref_audio", "ref_text", "voice_clone_prompt"}:
                offending.append(keyword.arg)
    assert not offending, (
        "TTS worker passes reference cloning into generation "
        f"({sorted(set(offending))}); measured to make the model speak the "
        "reference sentence instead of the request"
    )


def test_generation_config_disables_prompt_preprocessing() -> None:
    """preprocess_prompt=True is the documented trigger of the reference bleed."""
    text = SERVER.read_text(encoding="utf-8")
    assert "preprocess_prompt=False" in text, (
        "generation config must disable prompt preprocessing; with the default "
        "the worker speaks the reference phrase instead of the requested text"
    )


def test_synthesize_pins_russian_language() -> None:
    """The daily companion speaks Russian; the lane must not auto-detect."""
    node = _synthesize_node(_server_tree())
    languages: list[ast.expr | None] = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "generate":
            for keyword in call.keywords:
                if keyword.arg == "language":
                    languages.append(keyword.value)
    assert languages, "generate() must pin language='ru'"
    assert isinstance(languages[0], ast.Constant) and languages[0].value == "ru"