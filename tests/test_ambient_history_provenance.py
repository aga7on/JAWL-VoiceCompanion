import time
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer
from jawl_voicecompanion.ambient_segments import AmbientSegment, AmbientSegmenter
from jawl_voicecompanion.perception_fusion import PerceptionFusion
from jawl_voicecompanion.sensory_history import SensoryHistoryStore
from jawl_voicecompanion.streaming_perception import StreamingPerception


class Description:
    name = "fixture"

    def describe(self, pcm16, *, sample_rate, channels, clip_id):
        return {"kind": "music", "clip_id": clip_id, "duration_seconds": 2.0,
                "description": "Музыкальный фрагмент с ударными.", "tags": [],
                "mood": "", "confidence": 0.5}


class VoiceMem:
    def feed_audio(self, *args, **kwargs):
        return []

    def end_audio(self, *args, **kwargs):
        return []


def test_ambient_and_history_share_evidence_ids_for_forgetting(tmp_path):
    history = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
    memory = AmbientMemoryBuffer(enabled=True)
    fusion = PerceptionFusion(history_store=history)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion,
                                   audio_describer=Description())
    bridge.start("ambient-audio")
    try:
        end = time.monotonic()
        segment = AmbientSegment(segment_id="segment-42", session_id="ambient-audio",
                                 generation=bridge._generation, sequence=0, pcm16=b"\0\0" * 160,
                                 sample_rate=16000, channels=1, started_at=end - 2,
                                 ended_at=end, timestamp_source="host_pipe_receipt_monotonic")
        result = bridge._commit_transcript(segment, "В игре появился новый важный квест", confidence=0,
                                           event_id=segment.segment_id)
        assert result["status"] == "retained"
        bridge._process_description(segment, "ambient-audio")
        observations = memory.observations()
        assert len(observations) == 2
        transcript_id, music_id = [item["event_id"] for item in observations]
        assert transcript_id != music_id
        assert "новый важный квест" in history.context_text(seconds=3600)
        assert "фрагмент с ударными" in history.context_text(seconds=3600)
        history.flush()
        reopened = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
        assert reopened.redact([transcript_id])["recent_events"] == 1
        assert "новый важный квест" not in reopened.context_text(seconds=3600)
        assert "фрагмент с ударными" in reopened.context_text(seconds=3600)
        assert reopened.redact([music_id])["recent_events"] == 1
        assert "фрагмент с ударными" not in reopened.context_text(seconds=3600)
    finally:
        bridge.stop("ambient-audio", flush=False)


@pytest.mark.parametrize("use_smtc", [False, True], ids=["yamnet", "smtc"])
def test_music_evidence_ids_survive_coalescing_reload_and_redaction(tmp_path, use_smtc):
    class Smtc:
        def poll(self, **kwargs):
            return {"has_active_playback": True, "title": "Music Fixture", "artist": "Fixture"}

    path = tmp_path / "history.json"
    history = SensoryHistoryStore(path, enabled=True)
    memory = AmbientMemoryBuffer(enabled=True)
    fusion = PerceptionFusion(history_store=history)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion,
                                   smtc_adapter=Smtc() if use_smtc else None)
    bridge.start("ambient-audio")
    try:
        end = time.monotonic()
        soundscape = {"kind": "music", "description": "Музыка", "confidence": 0.7,
                      "duration_seconds": 2, "tags": [], "windows": 2, "music_windows": 2}
        for number in range(2):
            segment = AmbientSegment(segment_id=f"segment-{number}", session_id="ambient-audio",
                                     generation=bridge._generation, sequence=number, pcm16=b"\0\0" * 160,
                                     sample_rate=16000, channels=1, started_at=end - 2,
                                     ended_at=end + number, timestamp_source="host_pipe_receipt_monotonic")
            assert bridge._ingest_soundscape(soundscape, segment, "ambient-audio", music_frame={"state": "music"})
        ids = [o["event_id"] for o in memory.observations()]
        assert ids == [f"segment-{i}:{'smtc' if use_smtc else 'yamnet'}" for i in range(2)]
        history.flush()
        reopened = SensoryHistoryStore(path, enabled=True)
        items = list(reopened._recent)
        music = [item for item in items if item["modality"] == "music"]
        assert len(music) == 1
        assert set(music[0]["evidence_ids"]) == set(ids)
        assert music[0]["sample_count"] == 2
        assert reopened.redact([ids[1]])["recent_events"] == 1
        assert not [item for item in reopened._recent if item["modality"] == "music"]
        reopened.flush()
        assert not list(SensoryHistoryStore(path, enabled=True)._recent)
    finally:
        bridge.stop("ambient-audio", flush=False)


@pytest.mark.parametrize("condition", ["paused", "disabled", "private_title", "private_album", "private_description"])
def test_denied_soundscape_does_not_publish_to_fusion_or_history(tmp_path, condition):
    class Smtc:
        def poll(self, **kwargs):
            return {"has_active_playback": True,
                    "title": "password abc" if condition == "private_title" else "Safe title",
                    "album": "secret 123" if condition == "private_album" else "Safe album"}

    history = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
    fusion = PerceptionFusion(history_store=history)
    memory = AmbientMemoryBuffer(enabled=True)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion,
                                   smtc_adapter=Smtc() if condition in {"private_title", "private_album"} else None)
    bridge.start("ambient-audio")
    try:
        end = time.monotonic()
        segment = AmbientSegment(segment_id="denied", session_id="ambient-audio", generation=bridge._generation,
                                 sequence=0, pcm16=b"\0\0", sample_rate=16000, channels=1,
                                 started_at=end - 2, ended_at=end)
        if condition == "paused":
            memory.pause()
        elif condition == "disabled":
            memory.set_enabled(False)
        soundscape = {"kind": "music", "description": "secret text" if condition == "private_description" else "Music",
                      "confidence": 0.7, "duration_seconds": 2, "windows": 1, "music_windows": 1,
                      "event_candidates": [{"label": "music", "score": 0.8}]}
        assert not bridge._ingest_soundscape(soundscape, segment, "ambient-audio", music_frame={"state": "music"})
        assert not memory.observations()
        assert not list(history._recent)
        assert not fusion.current_state("music")["fresh"]
        assert not fusion.current_state("audio_event_candidates")["fresh"]
        if condition in {"private_title", "private_album"}:
            assert bridge.poll_smtc() is None
    finally:
        bridge.stop("ambient-audio", flush=False)


@pytest.mark.parametrize("status", ["duplicate", "rate_limited"])
def test_nonprivacy_retention_failure_keeps_live_observation(tmp_path, status):
    class Memory(AmbientMemoryBuffer):
        def ingest_audio_description(self, *args, **kwargs):
            return {"status": status, "event_id": kwargs.get("event_id")}

    memory = Memory(enabled=True)
    history = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
    fusion = PerceptionFusion(history_store=history)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion)
    bridge.start("ambient-audio")
    try:
        end = time.monotonic()
        segment = AmbientSegment(segment_id="valid", session_id="ambient-audio", generation=bridge._generation,
                                 sequence=0, pcm16=b"\0\0", sample_rate=16000, channels=1,
                                 started_at=end - 1, ended_at=end)
        soundscape = {"kind": "music", "description": "Music", "confidence": 0.7,
                      "duration_seconds": 1, "windows": 1, "music_windows": 1}
        bridge._ingest_soundscape(soundscape, segment, "ambient-audio", music_frame={"state": "music"})
        assert fusion.current_state("music")["fresh"]
        if status == "duplicate":
            assert fusion.current_state("music")["metadata"]["event_id"] == "valid:yamnet"
    finally:
        bridge.stop("ambient-audio", flush=False)


@pytest.mark.parametrize("action", ["pause", "pause_resume", "disable_enable", "clear", "stop"])
def test_blocked_smtc_poll_cannot_delay_pause_or_publish_after_stop(tmp_path, action):
    entered, release = Event(), Event()

    class SlowSmtc:
        def poll(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return {"has_active_playback": True, "title": "Late track"}

    memory = AmbientMemoryBuffer(enabled=True)
    history = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
    fusion = PerceptionFusion(history_store=history)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion, smtc_adapter=SlowSmtc())
    bridge.start("ambient-audio")
    end = time.monotonic()
    segment = AmbientSegment(segment_id="late", session_id="ambient-audio", generation=bridge._generation,
                             sequence=0, pcm16=b"\0\0", sample_rate=16000, channels=1,
                             started_at=end - 1, ended_at=end)
    soundscape = {"kind": "music", "description": "Music", "confidence": 0.7, "duration_seconds": 1}
    worker = Thread(target=bridge._ingest_soundscape, args=(soundscape, segment, "ambient-audio"),
                    kwargs={"music_frame": {"state": "music"}})
    worker.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        if action == "pause":
            memory.pause()
        elif action == "pause_resume":
            memory.pause()
            memory.resume()
        elif action == "disable_enable":
            memory.set_enabled(False)
            memory.set_enabled(True)
        elif action == "clear":
            memory.clear()
        else:
            bridge.stop("ambient-audio", flush=False, timeout=0.2)
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        worker.join(2)
        if action != "stop":
            bridge.stop("ambient-audio", flush=False)
    assert not worker.is_alive()
    assert not memory.observations()
    assert not list(history._recent)
    assert not fusion.current_state("music")["fresh"]


def test_direct_smtc_poll_discards_result_after_pause_resume(tmp_path):
    entered, release = Event(), Event()

    class SlowSmtc:
        def poll(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return {"has_active_playback": True, "title": "Late track"}

    memory = AmbientMemoryBuffer(enabled=True)
    history = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
    fusion = PerceptionFusion(history_store=history)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion, smtc_adapter=SlowSmtc())
    results = []
    worker = Thread(target=lambda: results.append(bridge.poll_smtc()))
    worker.start()
    try:
        assert entered.wait(1)
        memory.pause()
        memory.resume()
    finally:
        release.set()
        worker.join(2)
    assert results == [None]
    assert not list(history._recent)
    assert not fusion.current_state("music")["fresh"]


@pytest.mark.parametrize("lane", ["asr", "description"])
@pytest.mark.parametrize("action", ["pause_resume", "disable_enable", "clear"])
def test_delayed_audio_inference_discards_previous_privacy_epoch(tmp_path, lane, action):
    entered, release = Event(), Event()

    class SlowAsr:
        def feed_audio(self, *args, **kwargs):
            pass
        def finish(self, session_id):
            entered.set()
            assert release.wait(5)
            return {"text": "В игре произошло важное событие"}

    class SlowDescription(Description):
        def describe(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return super().describe(*args, **kwargs)

    memory = AmbientMemoryBuffer(enabled=True)
    history = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
    fusion = PerceptionFusion(history_store=history)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion,
                                   final_asr=SlowAsr() if lane == "asr" else None,
                                   audio_describer=SlowDescription() if lane == "description" else None)
    bridge.start("ambient-audio")
    end = time.monotonic()
    segment = AmbientSegment(segment_id="old", session_id="ambient-audio", generation=bridge._generation,
                             sequence=0, pcm16=b"\0\0" * 160, sample_rate=16000, channels=1,
                             started_at=end - 1, ended_at=end, privacy_epoch=memory._privacy_epoch)
    target = (lambda: bridge._process_segment(segment)) if lane == "asr" else (
        lambda: bridge._process_description(segment, "ambient-audio"))
    worker = Thread(target=target)
    worker.start()
    try:
        assert entered.wait(1)
        if action == "pause_resume":
            memory.pause()
            memory.resume()
        elif action == "disable_enable":
            memory.set_enabled(False)
            memory.set_enabled(True)
        else:
            memory.clear()
    finally:
        release.set()
        worker.join(2)
        bridge.stop("ambient-audio", flush=False)
    assert not worker.is_alive()
    assert not memory.observations()
    assert not list(history._recent)
    assert not fusion.current_state("speech")["fresh"]
    assert not fusion.current_state("audio_description")["fresh"]


def test_old_queued_segment_is_rejected_before_inference(tmp_path):
    class CountingAsr:
        def __init__(self): self.calls = 0
        def feed_audio(self, *args, **kwargs): self.calls += 1
        def finish(self, session_id): self.calls += 1; return {"text": "not expected"}

    memory = AmbientMemoryBuffer(enabled=True)
    asr = CountingAsr()
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, final_asr=asr)
    bridge.start("ambient-audio")
    try:
        end = time.monotonic()
        queued = AmbientSegment(segment_id="queued", session_id="ambient-audio", generation=bridge._generation,
                                sequence=0, pcm16=b"\0\0", sample_rate=16000, channels=1,
                                started_at=end - 1, ended_at=end, privacy_epoch=memory._privacy_epoch)
        memory.pause()
        memory.resume()
        bridge._process_segment(queued)
        assert asr.calls == 0
        assert not memory.observations()
    finally:
        bridge.stop("ambient-audio", flush=False)


def test_segmenter_does_not_join_pcm_across_privacy_epochs():
    segments = []
    segmenter = AmbientSegmenter(segments.append, max_segment_seconds=5)
    segmenter.start("ambient-audio")
    try:
        assert segmenter.submit(b"\x01\x00" * 100, 16000, 1, privacy_epoch=3)["status"] == "accepted"
        assert segmenter.submit(b"\x02\x00" * 100, 16000, 1, privacy_epoch=4)["status"] == "accepted"
    finally:
        segmenter.stop(flush=True)
    assert len(segments) == 1
    assert segments[0].privacy_epoch == 4
    assert segments[0].pcm16 == b"\x02\x00" * 100


def test_stream_tap_discards_inflight_and_partial_old_audio_after_pause(tmp_path):
    entered, release = Event(), Event()

    class Cortex:
        def embed_audio_pcm16(self, clip, sample_rate):
            if clip.startswith(b"\x01\x00"):
                entered.set()
                assert release.wait(5)
            return [0.0]

    class Transcriber:
        def transcribe_pcm16(self, clip, **kwargs): return clip
        def visual_transcript(self, clip, **kwargs):
            return "old audio" if clip.startswith(b"\x01\x00") else "new audio"

    memory = AmbientMemoryBuffer(enabled=True)
    history = SensoryHistoryStore(tmp_path / "history.json", enabled=True)
    fusion = PerceptionFusion(history_store=history)
    bridge = AmbientAudioASRBridge(VoiceMem(), memory, perception_fusion=fusion)
    service = SimpleNamespace(bridge=bridge)
    stream = StreamingPerception(screen_capture=None, cortex=Cortex(), describer=None,
                                 transcriber=Transcriber(), fusion=fusion, ambient_audio=service)
    bridge.start("ambient-audio")
    stream.start()
    try:
        old = b"\x01\x00" * 16000
        assert bridge.consume(old, 16000, 1, "ambient-audio", captured_at=time.monotonic())["status"] == "accepted"
        assert entered.wait(2)
        memory.pause()
        memory.resume()
        new = b"\x02\x00" * 16000
        assert bridge.consume(new, 16000, 1, "ambient-audio", captured_at=time.monotonic())["status"] == "accepted"
        release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and "new audio" not in history.context_text(seconds=60):
            time.sleep(0.02)
        text = history.context_text(seconds=60)
        assert "new audio" in text
        assert "old audio" not in text

        # A partial buffer from the old epoch cannot be completed by new PCM.
        stream.consume_audio(b"\x01\x00" * 8000, 16000, 1, "ambient-audio",
                             captured_at=time.monotonic(), privacy_epoch=memory._privacy_epoch)
        memory.pause()
        memory.resume()
        stream.consume_audio(b"\x02\x00" * 8000, 16000, 1, "ambient-audio",
                             captured_at=time.monotonic(), privacy_epoch=memory._privacy_epoch)
        assert len(stream._audio_buffer) == 16000
        assert stream._audio_buffer == b"\x02\x00" * 8000
    finally:
        release.set()
        stream.stop()
        bridge.stop("ambient-audio", flush=False)
