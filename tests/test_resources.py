import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.resources import ResourceGovernor  # noqa: E402


def test_resource_governor_prioritizes_conversation_over_background():
    governor = ResourceGovernor(profile="low")
    assert governor.try_acquire("speech") is True
    assert governor.try_acquire("speech") is False
    assert governor.try_acquire("ambient", background=True) is False
    governor.release("speech")
    assert governor.state()["active"] == {}


def test_gaming_mode_pauses_background_without_blocking_speech():
    governor = ResourceGovernor()
    governor.configure(gaming_mode=True)
    assert governor.try_acquire("ambient", background=True) is False
    assert governor.try_acquire("speech") is True
    governor.release("speech")
