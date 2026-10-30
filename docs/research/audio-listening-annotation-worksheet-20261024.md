# Human listening worksheet: five audio clips

**Purpose:** collect independent human audio labels for later evaluation of ASR, music detection and sound-event description. This worksheet contains no model predictions. The earlier provisional CSV was used only to confirm the five case IDs; none of its event labels, spans, language guesses or confidence values were copied here.

## Instructions for annotators

Listen to each local source clip in its entirety. The montage coordinates below come from `runtime/multimodal-realclips-20261024/manifest.json`; each source excerpt is ten seconds long. Enter all event times in both **clip-local seconds** (0–10) and, if useful, **montage seconds**. Use half-open intervals `[start,end)`. Events may overlap: annotate speech, music, vocals and effects independently.

Do not infer that a sound is absent because it is quiet or hard to understand. Mark `uncertain` when you cannot decide. Mark silence only when the interval is audibly silent; distinguish digital silence from quiet ambience. Do not guess lyrics, language, genre or instruments. Transcribe only intelligible words and mark unintelligible spans explicitly. A second listener should independently annotate speech/vocal boundaries and adjudicate disagreements.

Confidence scale: **3 = clear**, **2 = probable**, **1 = weak/uncertain**. Confidence is the listener's confidence in that annotation, not model confidence.

## Fixed cases

The fixed montage segments and source offsets are copied from the manifest. All answer fields remain blank for the human listener.

| Case ID | Clip/source | Montage interval | Source interval | Speech transcript / language / intelligibility | Music present? / audible style | Instrumental, sung vocal, or both? | Audible instruments / effects | Energy or tempo change | Confidence / uncertainty / notes |
|---|---|---:|---:|---|---|---|---|---|---|
| 01_ru_trailer | Russian live-action film trailer — “Здравствуй, грусть” | 0–10 s | 35–45 s |  |  |  |  |  |  |
| 02_anime | “Noblesse” official Russian trailer | 10–20 s | 20–30 s |  |  |  |  |  |  |
| 03_gameplay | Electric Noosphere RTS combat | 20–30 s | 0–10 s |  |  |  |  |  |  |
| 04_coding_ui | “100x coding with Cline + Requesty” | 30–40 s | 0–10 s |  |  |  |  |  |  |
| 05_aqua_song | Aqua — “Roses Are Red” | 40–50 s | 50–60 s |  |  |  |  |  |  |

## Timestamped event-boundary log

Add one row for each audible event or change. Use separate rows for overlapping sources, such as dialogue over music. Enter an explicit row for silence only when heard. Duplicate this blank block as needed.

| Case ID | Start, clip-local (s) | End, clip-local (s) | Start, montage (s) | End, montage (s) | Speech / exact words or unintelligible | Language | Music present? / style if clear | Instrumental / sung vocal / both | Audible instrument(s) or effect(s) | Energy / tempo change | Confidence (1–3) | Uncertain details / notes |
|---|---:|---:|---:|---:|---|---|---|---|---|---|---:|---|
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |  |  |

## Adjudication notes

| Case ID | Disputed interval | Annotator A | Annotator B | Adjudicated label / span | Reason or remaining uncertainty |
|---|---|---|---|---|---|
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |

## Session metadata

- Annotator:
- Review date:
- Headphones / playback setup:
- Number of full listens per clip:
- Playback speed (normally 1.0×):
- Any clipping, playback issue or inaudible segment:
- Notes about uncertainty or disagreements:

**Source of fixed case/timing metadata:** `runtime/multimodal-realclips-20261024/manifest.json`. The montage is local evaluation material and should not be redistributed.
