"""Refined speaker graph with bidirectional acoustic-visual exclusivity."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
import onnxruntime as ort


class RefinedAudioVisualSpeakerGraph:
    def __init__(self, model_path: str, sim_threshold: float = 0.52):
        self.sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.sim_threshold = sim_threshold
        self.audio_clusters: list[dict] = []  # {'id', 'centroid', 'exemplars', 'bound_character'}
        self.char_to_audio: dict[str, str] = {}  # character_id -> audio_speaker_id
        self.latencies_ms: list[float] = []

    def extract_audio_embedding(self, slice_wav: torch.Tensor) -> np.ndarray:
        fbank = kaldi.fbank(slice_wav, num_mel_bins=80)
        inp = fbank.unsqueeze(0).numpy()
        emb = self.sess.run(None, {"x": inp})[0][0]
        emb = emb / (np.linalg.norm(emb) + 1e-8)
        return emb

    def cluster_audio(self, emb: np.ndarray) -> tuple[str, float]:
        best_sim = -1.0
        best_idx = -1
        for idx, c in enumerate(self.audio_clusters):
            sim = float(np.dot(emb, c["centroid"]))
            if sim > best_sim:
                best_sim = sim
                best_idx = idx

        if best_sim >= self.sim_threshold and best_idx >= 0:
            c = self.audio_clusters[best_idx]
            c["exemplars"].append(emb)
            c["centroid"] = 0.85 * c["centroid"] + 0.15 * emb
            c["centroid"] /= (np.linalg.norm(c["centroid"]) + 1e-8)
            return c["id"], best_sim
        else:
            new_id = f"speaker_audio_{len(self.audio_clusters) + 1:02d}"
            self.audio_clusters.append({
                "id": new_id,
                "centroid": emb.copy(),
                "exemplars": [emb],
                "bound_character": None,
            })
            return new_id, 1.0

    def get_cluster(self, audio_id: str) -> dict | None:
        for c in self.audio_clusters:
            if c["id"] == audio_id:
                return c
        return None

    def process_turn_oracle(
        self,
        turn_id: int,
        start_sec: float,
        end_sec: float,
        emb: np.ndarray,
        gt_frames: dict[int, dict],
    ) -> dict:
        audio_id, audio_sim = self.cluster_audio(emb)
        cluster = self.get_cluster(audio_id)

        # Gather visible and speaking characters
        vis_chars = set()
        speaking_chars = set()
        for f in gt_frames.values():
            if start_sec <= f["timestamp_sec"] <= end_sec:
                for c in f["characters"]:
                    cid = c["character_id"]
                    vis_chars.add(cid)
                    if c["visual_state"] == "speaking":
                        speaking_chars.add(cid)

        bound_char = cluster.get("bound_character") if cluster else None

        # Check 1: Voice cluster already bound to a character
        if bound_char is not None:
            if bound_char in vis_chars:
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": audio_id,
                    "character_id": bound_char,
                    "visual_track_id": f"gt_{bound_char}",
                    "is_offscreen": False,
                    "binding_status": "confirmed_present",
                    "confidence": 0.90,
                }
            else:
                # Confirmed character is offscreen!
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": audio_id,
                    "character_id": bound_char,
                    "visual_track_id": None,
                    "is_offscreen": True,
                    "binding_status": "confirmed_from_history",
                    "confidence": 0.88,
                }

        # Check 2: Voice cluster is UNBOUND
        # Filter speaking candidates: if a candidate character is ALREADY bound to a DIFFERENT audio cluster,
        # and this cluster's centroid has low similarity to that character's voice centroid, reject candidate!
        valid_speaking_cands = []
        for c in speaking_chars:
            if c in self.char_to_audio:
                prev_audio_id = self.char_to_audio[c]
                prev_cluster = self.get_cluster(prev_audio_id)
                if prev_cluster is not None:
                    sim_to_prev = float(np.dot(emb, prev_cluster["centroid"]))
                    if sim_to_prev < self.sim_threshold:
                        # Mismatch! This voice cannot be character c!
                        continue
            valid_speaking_cands.append(c)

        if len(valid_speaking_cands) == 1:
            active_c = valid_speaking_cands[0]
            cluster["bound_character"] = active_c
            self.char_to_audio[active_c] = audio_id
            return {
                "turn_id": turn_id,
                "speaker_audio_id": audio_id,
                "character_id": active_c,
                "visual_track_id": f"gt_{active_c}",
                "is_offscreen": False,
                "binding_status": "active_speaker_present",
                "confidence": 0.92,
            }
        elif len(valid_speaking_cands) > 1:
            return {
                "turn_id": turn_id,
                "speaker_audio_id": audio_id,
                "character_id": "speaker_unknown",
                "visual_track_id": None,
                "is_offscreen": False,
                "binding_status": "ambiguous_multiple_speakers",
                "confidence": 0.30,
            }
        else:
            # 0 valid speaking candidates
            # Either no one speaking on screen, or onscreen characters' voice profile conflicts!
            # It must be an offscreen voice!
            return {
                "turn_id": turn_id,
                "speaker_audio_id": audio_id,
                "character_id": "speaker_unknown",
                "visual_track_id": None,
                "is_offscreen": True,
                "binding_status": "unbound_offscreen",
                "confidence": 0.50,
            }


def test_refined():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    wav_path = Path("runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav")
    model_path = Path("runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)

    wav_np, sr = sf.read(wav_path)
    waveform = torch.from_numpy(wav_np).float().unsqueeze(0)

    events = gt["speech_events"]
    gt_frames = {f["frame_idx"]: f for f in gt["frames"]}

    graph = RefinedAudioVisualSpeakerGraph(str(model_path), sim_threshold=0.55)
    results = []

    for e in events:
        s = int(e["start_sec"] * sr)
        end = int(e["end_sec"] * sr)
        sl = waveform[:, s:end]
        emb = graph.extract_audio_embedding(sl)
        res = graph.process_turn_oracle(
            turn_id=e["turn_id"],
            start_sec=e["start_sec"],
            end_sec=e["end_sec"],
            emb=emb,
            gt_frames=gt_frames,
        )
        results.append(res)
        ok = "OK" if res["character_id"] == e["speaker"] else ("ABSTAIN" if res["character_id"] == "speaker_unknown" else "FAIL")
        print(f"Turn {e['turn_id']:2d}: True={e['speaker']:12s} | Pred={res['character_id']:14s} | TrueOff={str(e['is_offscreen']):5s} | PredOff={str(res['is_offscreen']):5s} | Status={res['binding_status']} | {ok}")

    t15 = results[14]
    print("\nTURN 15 RESULT:")
    print(t15)


if __name__ == "__main__":
    test_refined()
