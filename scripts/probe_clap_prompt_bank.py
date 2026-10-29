"""Prompt-robustness probe for pinned CPU CLAP ONNX; stores scores, not audio."""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
import psutil
from tokenizers import Tokenizer
from transformers import ClapFeatureExtractor

import probe_clap_candidate as base


PROMPT_BANKS = {
    "style": {
        "classical": [
            "Instrumental classical music performed on a pipe organ.",
            "A baroque classical organ performance with sustained chords and a measured melody.",
            "A solo pipe organ performing a classical composition.",
        ],
        "jazz": [
            "Instrumental jazz music with a saxophone solo.",
            "A jazz ensemble playing a saxophone-led tune.",
            "A saxophone performs an improvised jazz melody.",
        ],
        "rock": [
            "Rock music with electric guitars, bass and drums.",
            "A rock band plays a loud electric guitar song.",
            "Instrumental rock music driven by guitar and drums.",
        ],
        "pop": [
            "A pop song with a lead singer and rhythmic backing.",
            "Popular music with vocals, a steady beat and accompaniment.",
            "A singer performs a contemporary pop song.",
        ],
        "electronic_ambient": [
            "Ambient electronic instrumental music with synthesizers.",
            "A quiet atmospheric electronic music passage.",
            "Atmospheric synthesizer music with sustained electronic textures.",
        ],
        "cinematic_orchestral": [
            "A cinematic orchestral soundtrack with strings and brass.",
            "Dramatic instrumental film score played by an orchestra.",
            "An orchestral soundtrack builds with strings and percussion.",
        ],
        "game_score": [
            "Instrumental background music from a video game.",
            "A video game soundtrack plays in the background.",
            "Music composed as a soundtrack for a game scene.",
        ],
    },
    "timbre": {
        "pipe_organ": [
            "The sustained sound of a pipe organ playing a melody.",
            "A pipe organ performs chords and notes.",
            "A large church organ playing instrumental music.",
        ],
        "saxophone": [
            "A saxophone playing a melodic instrumental passage.",
            "The warm, reedy tone of a solo saxophone.",
            "A person performs a melody on a saxophone.",
        ],
        "electric_guitar": [
            "An electric guitar playing a musical riff.",
            "Distorted electric guitar with bass and drums.",
            "A clean electric guitar plays a melody.",
        ],
        "synthesizer": [
            "Electronic synthesizer tones playing music.",
            "A sustained synthetic chord from a synthesizer.",
            "Ambient music played on electronic keyboards.",
        ],
        "piano": [
            "A piano playing an instrumental melody.",
            "Acoustic piano notes and chords are heard.",
            "A solo piano performs a classical passage.",
        ],
        "drums_percussion": [
            "A drum kit keeps a rhythmic beat in music.",
            "Percussion instruments play a repeating rhythm.",
            "Drums and cymbals are prominent in the music.",
        ],
        "bass_guitar": [
            "A bass guitar plays a repeating low musical line.",
            "Plucked electric bass supports the rhythm and harmony.",
            "A bassist performs a melodic groove under the song.",
        ],
        "synth_bass": [
            "A deep electronic synthesizer bass anchors the music.",
            "Pulsing synthetic sub-bass forms the low end of the track.",
            "A synthesized bass line moves with the musical rhythm.",
        ],
    },
    "scene": {
        "music_present": [
            "Music is audible, with melody, rhythm, instruments, or sustained musical tones.",
            "A musical performance or soundtrack can be heard in the recording.",
            "A music bed with acoustic instruments or electronic tones plays in the audio.",
        ],
        "speech_dominant": [
            "One person or several people speak as the foreground sound.",
            "Conversational speech or narration is prominent in the audio.",
            "A spoken voice carries most of the audible scene.",
        ],
        "environmental_sounds": [
            "Environmental ambience, natural sounds, machinery, or game effects are audible.",
            "The recording contains room ambience and environmental sound events.",
            "Mechanical, nature, or game sound effects form the audible scene.",
        ],
        "speech_and_music": [
            "Human speech and a musical soundtrack overlap in the same recording.",
            "Voices and background music are both audible at once.",
            "Spoken dialogue is heard over music playing underneath.",
        ],
        "game_effects": [
            "A video game produces impacts, interface sounds, movement, and other effects.",
            "Electronic game sound effects occur around the gameplay audio.",
            "Game actions create audible effects such as impacts, alerts, and movement.",
        ],
        "steady_noise": [
            "Broadband static noise fills the recording.",
            "A steady hiss or noisy signal is audible.",
            "White noise continues through the audio sample.",
        ],
        "near_silence": [
            "The recording is at digital silence or near silence.",
            "The audio contains only an extremely quiet background floor.",
            "Almost no sound energy is present in the recording.",
        ],
    },
    "vocal_content": {
        "lead_singing": [
            "A lead singer performs a melodic vocal line over music.",
            "A prominent sung voice carries the melody of a song.",
            "A singer performs the main vocal part over musical accompaniment.",
        ],
        "wordless_vocal": [
            "A human voice sings sustained wordless vowel sounds in a musical phrase.",
            "Wordless singing blends with the instrumental music.",
            "A voice performs melodic vocalizations over a musical bed.",
        ],
        "choir_vocals": [
            "A group choir sings together over musical accompaniment.",
            "Layered backing singers harmonize with the music.",
            "Several voices sing a coordinated harmony in the song.",
        ],
        "rap_vocal": [
            "Rhythmic rap vocals are performed over a musical beat.",
            "A rapper delivers rhythmic words over bass and percussion.",
            "A spoken rhythmic vocal performance rides over a beat.",
        ],
    },
    "drums_percussion": {
        "acoustic_drum_kit": [
            "An acoustic drum kit plays a steady musical beat.",
            "Kick drum, snare, and cymbals drive the rhythm.",
            "A drummer performs a repeating groove on a drum kit.",
        ],
        "electronic_drum_machine": [
            "Programmed electronic drums create a precise rhythmic beat.",
            "A drum machine and synthetic percussion shape the music.",
            "Electronic percussion provides the track's repeating rhythm.",
        ],
        "orchestral_percussion": [
            "Orchestral percussion such as timpani and cymbals accents the score.",
            "Percussion instruments punctuate a cinematic orchestral passage.",
            "Timpani and orchestral drums add weight to the soundtrack.",
        ],
        "hand_percussion": [
            "Hand percussion and small drums play a repeating musical rhythm.",
            "Congas, shakers, or hand drums accompany the music.",
            "A percussionist plays a hand drum groove with shakers.",
        ],
    },
    "bass": {
        "bass_guitar": [
            "A bass guitar plays a repeating low musical line.",
            "Plucked electric bass supports the rhythm and harmony.",
            "A bassist performs a melodic groove under the song.",
        ],
        "synth_bass": [
            "A deep electronic synthesizer bass anchors the music.",
            "Pulsing synthetic sub-bass forms the low end of the track.",
            "A synthesized bass line moves with the musical rhythm.",
        ],
        "acoustic_low_strings": [
            "Low acoustic strings provide a resonant bass line.",
            "Cello or upright bass carries the low musical register.",
            "A bowed low string instrument supports the harmony.",
        ],
    },
    "electronic_timbre": {
        "synth_pad": [
            "Sustained electronic synthesizer pads create a soft musical texture.",
            "Warm ambient synth chords fill the musical background.",
            "Long electronic tones form a layered atmospheric pad.",
        ],
        "synth_lead": [
            "A bright electronic synthesizer lead plays the main melody.",
            "A synthesizer performs a clear melodic line over the beat.",
            "A lead synth plays a repeating hook in the music.",
        ],
        "synth_arpeggio": [
            "Repeating electronic arpeggios form a rhythmic musical pattern.",
            "Sequenced synthesizer notes pulse in a repeating pattern.",
            "A fast synth sequence plays a regular arpeggiated figure.",
        ],
        "chiptune": [
            "Bright retro video game chiptune tones play a melody.",
            "An 8-bit electronic game soundtrack uses synthetic tones.",
            "Retro arcade-style electronic notes form a game melody.",
        ],
    },
}


def _session(path: Path) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def _text_embedding(tokenizer: Tokenizer, session: ort.InferenceSession, phrase: str) -> np.ndarray:
    inputs = base.make_text_inputs(tokenizer, phrase)
    names = {item.name for item in session.get_inputs()}
    feeds = {name: value for name, value in inputs.items() if name in names}
    if set(feeds) != names:
        raise RuntimeError(f"Unexpected text input names: {sorted(names)}")
    vector = np.asarray(session.run(None, feeds)[0], dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm < 1e-8:
        raise RuntimeError("Invalid text embedding")
    return vector / norm


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=base.ROOT / "runtime/audio-path-replay/out/clap-prompt-bank-probe-20261026-positive.json",
    )
    args = parser.parse_args()
    model_dir = base.MODEL_DIR
    audio_path = model_dir / "clap_audio.onnx"
    text_path = model_dir / "clap_text.onnx"
    tokenizer_path = model_dir / "tokenizer.json"
    expected = {
        "clap_audio.onnx": "3f42f71e555b62709910b6efa66fa5879f00d9571874b12b0fa674f82dbfe332",
        "clap_text.onnx": "c07b27204836877d5b615c103685b66ea8f21bc6b5b70a572be356125423a8bf",
        "tokenizer.json": "4fd1d86b4f5b53f40a609fcd11c1f34024b735f870a07439d70202b98493661a",
    }
    paths = (audio_path, text_path, tokenizer_path)
    hashes = {path.name: base.sha256(path) for path in paths}
    if hashes != expected:
        raise RuntimeError(f"Pinned artifact SHA mismatch: {hashes}")

    process = psutil.Process()
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    audio = _session(audio_path)
    text = _session(text_path)
    if audio.get_providers() != ["CPUExecutionProvider"] or text.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("CLAP must use CPUExecutionProvider only")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    sessions_loaded_at = time.perf_counter()
    rss_after_load = process.memory_info().rss
    prototype_start = time.perf_counter()
    prototypes: dict[str, dict[str, np.ndarray]] = {}
    prompt_consistency: dict[str, dict[str, dict[str, float]]] = {}
    for group, labels in PROMPT_BANKS.items():
        prototypes[group] = {}
        prompt_consistency[group] = {}
        for label, phrases in labels.items():
            vectors = np.stack([_text_embedding(tokenizer, text, phrase) for phrase in phrases])
            prototype = vectors.mean(axis=0)
            prototype /= max(float(np.linalg.norm(prototype)), 1e-8)
            prototypes[group][label] = prototype
            similarities = vectors @ prototype
            prompt_consistency[group][label] = {
                "mean_cosine_to_prototype": float(np.mean(similarities)),
                "min_cosine_to_prototype": float(np.min(similarities)),
            }
    prototype_seconds = time.perf_counter() - prototype_start
    rss_after_text = process.memory_info().rss
    extractor = ClapFeatureExtractor()
    audio_input = audio.get_inputs()[0].name
    results = []
    inference_ms = []
    for case, (path, expected_probe) in base.CASES.items():
        if not path.is_file():
            results.append({"case": case, "available": False, "expected_probe": expected_probe})
            continue
        waveform = base.decode(path, 8.0)
        features = extractor(
            waveform, sampling_rate=48000, truncation="rand_trunc", padding="pad", return_tensors="np"
        )["input_features"]
        started_one = time.perf_counter()
        vector = np.asarray(audio.run(None, {audio_input: features})[0], dtype=np.float32).reshape(-1)
        inference_ms.append((time.perf_counter() - started_one) * 1000.0)
        vector /= max(float(np.linalg.norm(vector)), 1e-8)
        rankings: dict[str, list[dict[str, float | str]]] = {}
        margins: dict[str, float] = {}
        for group, labels in prototypes.items():
            scores = sorted(
                ((label, float(np.dot(vector, prototype))) for label, prototype in labels.items()),
                key=lambda row: row[1], reverse=True,
            )
            rankings[group] = [{"label": label, "cosine_similarity": score} for label, score in scores]
            margins[group] = scores[0][1] - scores[1][1] if len(scores) > 1 else 0.0
        results.append({
            "case": case,
            "available": True,
            "expected_probe": expected_probe,
            "rms": float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64)))),
            "top_by_group": {group: rows[:3] for group, rows in rankings.items()},
            "top_margin_by_group": margins,
        })
    output = args.output if args.output.is_absolute() else base.ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "ConceptualMachines/magda-sample-tagger CLAP HTSAT ONNX",
        "revision": "f24970352f239768aaad48cc8734fb298441a763",
        "artifact_sha256": hashes,
        "providers": {"audio": audio.get_providers(), "text": text.get_providers()},
        "threads": {"intra_op": 1, "inter_op": 1},
        "session_load_seconds": sessions_loaded_at - started,
        "prototype_seconds": prototype_seconds,
        "rss_mib_before_load": round(rss_before / 1024**2, 1),
        "rss_mib_after_model_load": round(rss_after_load / 1024**2, 1),
        "rss_mib_after_text_prototypes": round(rss_after_text / 1024**2, 1),
        "audio_encoder_ms_p50": round(float(np.median(inference_ms)), 2) if inference_ms else None,
        "audio_encoder_ms_p95": round(float(np.percentile(inference_ms, 95)), 2) if inference_ms else None,
        "prompt_consistency": prompt_consistency,
        "candidate_prompt_bank": PROMPT_BANKS,
        "weights_unchanged": True,
        "classification_design": "positive multi-class scene prompts with independent musical attribute banks",
        "limitations": [
            "existing small fixture set only; it is not source-disjoint, genre-balanced validation",
            "cosine similarities and margins are not calibrated confidence or probability",
            "averaging paraphrase embeddings reduces wording sensitivity but does not prove factuality",
            "CLAP returns semantic similarity scores, not generated captions",
            "no model was added to the daily profile and no raw PCM was written",
        ],
        "cases": results,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "prototype_seconds": round(prototype_seconds, 2),
        "rss_mib_after_text_prototypes": report["rss_mib_after_text_prototypes"],
        "audio_encoder_ms_p50": report["audio_encoder_ms_p50"],
        "audio_encoder_ms_p95": report["audio_encoder_ms_p95"],
        "cases": [{"case": row["case"], "top": row.get("top_by_group", {})} for row in results if row.get("available")],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
