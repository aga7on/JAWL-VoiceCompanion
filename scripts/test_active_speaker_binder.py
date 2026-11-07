"""Full simulation of Active Speaker Binding with Audio-Visual Association."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
import onnxruntime as ort
from scipy.optimize import linear_sum_assignment


class ActiveSpeakerBinder:
    def __init__(
        self,
        audio_model_path: str,
        audio_sim_threshold: float = 0.52,
    ):
        self.sess = ort.InferenceSession(audio_model_path, providers=["CPUExecutionProvider"])
        self.audio_sim_threshold = audio_sim_threshold
        self.audio_clusters: list[dict] = []  # {'id', 'centroid', 'exemplars', 'bound_character'}
        self.char_to_audio: dict[str, str] = {}
        self.latencies_ms: list[float] = []

    def extract_audio_embedding(self, slice_wav: torch.Tensor) -> np.ndarray:
        t0 = torch.cuda.Event(enable_timing=True) if torch.cuda.is_available() else None
        # Kaldi fbank
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

        if best_sim >= self.audio_sim_threshold and best_idx >= 0:
            c = self.audio_clusters[best_idx]
            # Don't let centroid drift excessively: weighted update
            c["exemplars"].append(emb)
            c["centroid"] = 0.8 * c["centroid"] + 0.2 * emb
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

    def bind_oracle_turn(
        self,
        turn_id: int,
        start_sec: float,
        end_sec: float,
        emb: np.ndarray,
        gt_frames: dict[int, dict],
        catalog: dict[str, dict],
    ) -> dict:
        audio_id, audio_sim = self.cluster_audio(emb)
        cluster = self.get_cluster(audio_id)

        # 1. Gather visible characters in the time interval
        vis_chars = set()
        speaking_chars = set()
        idle_chars = set()
        for f in gt_frames.values():
            if start_sec <= f["timestamp_sec"] <= end_sec:
                for c in f["characters"]:
                    cid = c["character_id"]
                    vis_chars.add(cid)
                    if c["visual_state"] == "speaking":
                        speaking_chars.add(cid)
                    elif c["visual_state"] in ("idle", "moving"):
                        idle_chars.add(cid)

        # 2. Check if this voice cluster has a previously confirmed character
        bound_char = cluster.get("bound_character") if cluster else None

        # Case 1: Exactly ONE character is actively speaking on screen
        if len(speaking_chars) == 1:
            active_c = list(speaking_chars)[0]
            # Bind voice to this character
            if cluster and cluster["bound_character"] is None:
                cluster["bound_character"] = active_c
                self.char_to_audio[active_c] = audio_id
            
            return {
                "turn_id": turn_id,
                "speaker_audio_id": audio_id,
                "character_id": active_c,
                "visual_track_id": f"track_{active_c}",
                "is_offscreen": False,
                "binding_status": "active_speaker_present",
                "confidence": 0.95,
            }

        # Case 2: Multiple characters speaking on screen (e.g. duet or rapid alternating)
        elif len(speaking_chars) > 1:
            # If voice cluster is already bound to one of them, use it!
            if bound_char and bound_char in speaking_chars:
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": audio_id,
                    "character_id": bound_char,
                    "visual_track_id": f"track_{bound_char}",
                    "is_offscreen": False,
                    "binding_status": "resolved_by_voice_history",
                    "confidence": 0.85,
                }
            # Otherwise ambiguous
            return {
                "turn_id": turn_id,
                "speaker_audio_id": audio_id,
                "character_id": "speaker_unknown",
                "visual_track_id": None,
                "is_offscreen": False,
                "binding_status": "ambiguous_multiple_speakers",
                "confidence": 0.30,
            }

        # Case 3: NO characters speaking on screen (listener reaction shot or empty frame)
        else:
            # Check if voice cluster is known from history!
            if bound_char:
                if bound_char in vis_chars:
                    # Visible but lips stopped or missed in annotation
                    return {
                        "turn_id": turn_id,
                        "speaker_audio_id": audio_id,
                        "character_id": bound_char,
                        "visual_track_id": f"track_{bound_char}",
                        "is_offscreen": False,
                        "binding_status": "confirmed_present_idle_lips",
                        "confidence": 0.80,
                    }
                else:
                    # NOT visible on screen -> OFFSCREEN speech by known character!
                    return {
                        "turn_id": turn_id,
                        "speaker_audio_id": audio_id,
                        "character_id": bound_char,
                        "visual_track_id": None,
                        "is_offscreen": True,
                        "binding_status": "confirmed_from_history",
                        "confidence": 0.90,
                    }
            else:
                # Voice not bound from history, and no one speaking on screen
                # -> Offscreen unknown! Never attribute to visible listeners!
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": audio_id,
                    "character_id": "speaker_unknown",
                    "visual_track_id": None,
                    "is_offscreen": True,
                    "binding_status": "unbound_offscreen",
                    "confidence": 0.50,
                }


def run_full_test():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    wav_path = Path("runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav")
    model_path = Path("runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)

    wav_np, sr = sf.read(wav_path)
    waveform = torch.from_numpy(wav_np).float().unsqueeze(0)

    events = gt["speech_events"]
    gt_frames = {f["frame_idx"]: f for f in gt["frames"]}
    catalog = gt["character_catalog"]

    binder = ActiveSpeakerBinder(str(model_path), audio_sim_threshold=0.52)

    results = []
    print(f"{'Turn':4s} | {'Time (s)':12s} | {'True Spk':12s} | {'Pred Spk':14s} | {'True Off':8s} | {'Pred Off':8s} | {'Binding Status':28s} | Match?")
    print("-" * 115)

    for e in events:
        s = int(e["start_sec"] * sr)
        end = int(e["end_sec"] * sr)
        sl = waveform[:, s:end]
        emb = binder.extract_audio_embedding(sl)
        res = binder.bind_oracle_turn(
            turn_id=e["turn_id"],
            start_sec=e["start_sec"],
            end_sec=e["end_sec"],
            emb=emb,
            gt_frames=gt_frames,
            catalog=catalog,
        )
        results.append(res)
        ok = "OK" if res["character_id"] == e["speaker"] else ("ABSTAIN" if res["character_id"] == "speaker_unknown" else "FAIL")
        t_span = f"{e['start_sec']:4.1f}-{e['end_sec']:4.1f}"
        print(f"{e['turn_id']:4d} | {t_span:12s} | {e['speaker']:12s} | {res['character_id']:14s} | {str(e['is_offscreen']):8s} | {str(res['is_offscreen']):8s} | {res['binding_status']:28s} | {ok}")

    # Compute overall metrics
    correct = sum(1 for r, e in zip(results, events) if r["character_id"] == e["speaker"])
    abstain = sum(1 for r in results if r["character_id"] == "speaker_unknown")
    wrong = len(events) - correct - abstain
    
    # Offscreen metrics
    # Turn 15 is offscreen in GT
    offscreen_gt = [e for e in events if e["is_offscreen"]]
    offscreen_fp = sum(1 for r, e in zip(results, events) if e["is_offscreen"] and not r["is_offscreen"]) # misattributed to onscreen!
    offscreen_correct = sum(1 for r, e in zip(results, events) if e["is_offscreen"] and r["is_offscreen"])

    print("\n" + "=" * 60)
    print("ORACLE ASD (Active Speaker Binding) RESULTS:")
    print("=" * 60)
    print(f"Total Speech Turns: {len(events)}")
    print(f"Speaker Attribution Accuracy: {correct / len(events) * 100:.2f}% ({correct}/{len(events)})")
    print(f"Binding Coverage: {(len(events) - abstain) / len(events) * 100:.2f}% ({len(events) - abstain}/{len(events)})")
    print(f"Abstentions: {abstain} | Wrong Attributions: {wrong}")
    print(f"Offscreen False Attribution Rate: {offscreen_fp / len(offscreen_gt) * 100:.2f}% ({offscreen_fp}/{len(offscreen_gt)})")
    print(f"Voice Clusters Formed: {len(binder.audio_clusters)}")
    for c in binder.audio_clusters:
        print(f"  {c['id']}: bound to '{c['bound_character']}', {len(c['exemplars'])} turns")


if __name__ == "__main__":
    run_full_test()
