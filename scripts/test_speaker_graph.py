"""Prototype simulation of Audio-Visual Speaker Graph with historical binding."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
import onnxruntime as ort


class AudioVisualSpeakerGraph:
    def __init__(
        self,
        audio_model_path: str,
        audio_sim_threshold: float = 0.50,
        binding_confirm_threshold: float = 0.60,
    ):
        self.sess = ort.InferenceSession(audio_model_path, providers=["CPUExecutionProvider"])
        self.audio_sim_threshold = audio_sim_threshold
        self.binding_confirm_threshold = binding_confirm_threshold

        # Audio speakers: id -> {exemplars: list, centroid: np.ndarray, bound_character: str | None, conf: float}
        self.audio_speakers: dict[str, dict] = {}
        # Characters: id -> {bound_audio_id: str | None}
        self.character_bindings: dict[str, str] = {}
        self.next_audio_idx = 1

    def extract_audio_embedding(self, slice_wav: torch.Tensor) -> np.ndarray:
        fbank = kaldi.fbank(slice_wav, num_mel_bins=80)
        inp = fbank.unsqueeze(0).numpy()
        emb = self.sess.run(None, {"x": inp})[0][0]
        emb = emb / (np.linalg.norm(emb) + 1e-8)
        return emb

    def match_audio_speaker(self, emb: np.ndarray) -> tuple[str, float]:
        best_sim = -1.0
        best_id = None
        for spk_id, data in self.audio_speakers.items():
            sim = float(np.dot(emb, data["centroid"]))
            if sim > best_sim:
                best_sim = sim
                best_id = spk_id

        if best_sim >= self.audio_sim_threshold and best_id is not None:
            data = self.audio_speakers[best_id]
            data["exemplars"].append(emb)
            # Update centroid
            data["centroid"] = np.mean(data["exemplars"], axis=0)
            data["centroid"] = data["centroid"] / (np.linalg.norm(data["centroid"]) + 1e-8)
            return best_id, best_sim
        else:
            new_id = f"speaker_audio_{self.next_audio_idx:02d}"
            self.next_audio_idx += 1
            self.audio_speakers[new_id] = {
                "exemplars": [emb],
                "centroid": emb.copy(),
                "bound_character": None,
                "confidence": 0.0,
                "turn_count": 1,
            }
            return new_id, 1.0

    def process_turn_oracle(
        self,
        turn_id: int,
        start_sec: float,
        end_sec: float,
        slice_wav: torch.Tensor,
        gt_frames: dict[int, dict],
    ) -> dict:
        """Process one turn using Oracle visual frames (GT characters and visual states)."""
        emb = self.extract_audio_embedding(slice_wav)
        spk_audio_id, audio_sim = self.match_audio_speaker(emb)
        audio_info = self.audio_speakers[spk_audio_id]
        audio_info["turn_count"] = len(audio_info["exemplars"])

        # Visible characters during this turn
        vis_chars = set()
        speaking_chars = set()
        idle_chars = set()
        for f_idx, f in gt_frames.items():
            if start_sec <= f["timestamp_sec"] <= end_sec:
                for c in f["characters"]:
                    cid = c["character_id"]
                    vis_chars.add(cid)
                    if c["visual_state"] == "speaking":
                        speaking_chars.add(cid)
                    else:
                        idle_chars.add(cid)

        # Decision logic
        bound_char = audio_info.get("bound_character")
        
        # Case A: Historically confirmed voice
        if bound_char is not None:
            if bound_char in vis_chars:
                # Confirmed character is visible
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": spk_audio_id,
                    "character_id": bound_char,
                    "visual_track_id": f"gt_{bound_char}",
                    "is_offscreen": False,
                    "binding_status": "confirmed_present",
                    "confidence": audio_sim,
                }
            else:
                # Confirmed character is NOT visible (even if others are on screen!)
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": spk_audio_id,
                    "character_id": bound_char,
                    "visual_track_id": None,
                    "is_offscreen": True,
                    "binding_status": "confirmed_from_history",
                    "confidence": audio_sim,
                }

        # Case B: Unconfirmed voice -> seek evidence in current scene
        if len(speaking_chars) == 1:
            cand = list(speaking_chars)[0]
            # Bind if character not already bound to a conflicting audio speaker, or re-bind
            audio_info["bound_character"] = cand
            audio_info["confidence"] = 0.90
            self.character_bindings[cand] = spk_audio_id
            return {
                "turn_id": turn_id,
                "speaker_audio_id": spk_audio_id,
                "character_id": cand,
                "visual_track_id": f"gt_{cand}",
                "is_offscreen": False,
                "binding_status": "newly_confirmed",
                "confidence": 0.90,
            }
        elif len(speaking_chars) > 1:
            # Ambiguous: multiple characters speaking simultaneously
            return {
                "turn_id": turn_id,
                "speaker_audio_id": spk_audio_id,
                "character_id": "speaker_unknown",
                "visual_track_id": None,
                "is_offscreen": False,
                "binding_status": "ambiguous_multiple_speakers",
                "confidence": 0.30,
            }
        else:
            # No speaking characters visible
            if len(vis_chars) == 0:
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": spk_audio_id,
                    "character_id": "speaker_unknown",
                    "visual_track_id": None,
                    "is_offscreen": True,
                    "binding_status": "unbound_offscreen",
                    "confidence": 0.50,
                }
            else:
                # Characters visible, but none speaking (listener reaction shot)
                # DO NOT attribute to visible listener!
                return {
                    "turn_id": turn_id,
                    "speaker_audio_id": spk_audio_id,
                    "character_id": "speaker_unknown",
                    "visual_track_id": None,
                    "is_offscreen": True,
                    "binding_status": "offscreen_listener_on_screen",
                    "confidence": 0.60,
                }


def run_sim():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    wav_path = Path("runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav")
    model_path = Path("runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)

    wav_np, sr = sf.read(wav_path)
    waveform = torch.from_numpy(wav_np).float().unsqueeze(0)

    events = gt["speech_events"]
    gt_frames = {f["frame_idx"]: f for f in gt["frames"]}

    for thresh in [0.45, 0.48, 0.50, 0.52, 0.55]:
        graph = AudioVisualSpeakerGraph(str(model_path), audio_sim_threshold=thresh)
        results = []
        for e in events:
            s_samp = int(e["start_sec"] * sr)
            e_samp = int(e["end_sec"] * sr)
            sl = waveform[:, s_samp:e_samp]
            res = graph.process_turn_oracle(
                turn_id=e["turn_id"],
                start_sec=e["start_sec"],
                end_sec=e["end_sec"],
                slice_wav=sl,
                gt_frames=gt_frames,
            )
            results.append(res)

        correct = 0
        abstain = 0
        wrong = 0
        offscreen_fp = 0
        offscreen_tp = 0
        offscreen_fn = 0

        for r, e in zip(results, events):
            true_spk = e["speaker"]
            pred_spk = r["character_id"]
            true_off = e["is_offscreen"]
            pred_off = r["is_offscreen"]

            if true_off:
                if pred_off:
                    offscreen_tp += 1
                else:
                    offscreen_fn += 1
                    offscreen_fp += 1  # falsely assigned to onscreen!
            else:
                if pred_off:
                    pass

            if pred_spk == true_spk:
                correct += 1
            elif pred_spk == "speaker_unknown":
                abstain += 1
            else:
                wrong += 1

        acc = correct / len(events)
        cov = (len(events) - abstain) / len(events)
        print(f"Thresh {thresh:.2f}: Acc={acc*100:5.2f}% ({correct:2d}/{len(events)}) | Cov={cov*100:5.2f}% | Abstain={abstain:2d} | Wrong={wrong:2d} | Clusters={len(graph.audio_speakers)}")


if __name__ == "__main__":
    run_sim()
