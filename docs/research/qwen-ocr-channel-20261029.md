# Qwen visual sensor: OCR channel

## Change

The Qwen visual lane now asks the configured `ScreenCaptureAdapter` for Windows
OCR on the first capture, when a visual change is pending, and at the static
refresh cadence. It does not invoke OCR on every high-rate image poll. The
selected display, target-window, and focused-window capture paths can all return
OCR alongside the image; the OCR text remains independent from the VLM caption.

OCR items are joined into the bounded `ocr` channel with capture time, source,
scene ID, and `verified: false`. The existing VA packet renders OCR separately.
The channel has a 5 second current-context TTL and a 2400 character bound. A
scene invalidation invalidates earlier OCR; an empty OCR result also invalidates
the previous text so text from a prior screen does not linger as current.

The screen adapter applies configured pixel redactions before encoding the
image. OCR phrases matching configured sensitive terms produce redaction boxes;
matching OCR text and text overlapping a redaction box are omitted. The new
tests cover both filtering and bounded OCR cadence.

## Verification

Focused adapter, sensor, fusion, and packet suites: **61 passed**. The wider
screen/OCR, Qwen sensor, fusion, packet, native context, and web suite: **163
passed, 33 subtests passed**.

The automated suite uses a fake OCR provider. A one-shot live capture on display 0
(1920x1080) verified the installed Windows OCR provider and the full local
adapter -> QwenVisualSensor -> PerceptionFusion -> VA-packet handoff: one sensor
capture, one fake Qwen submission, a fresh separate OCR channel (819 chars), and
OCR present in the rendered brain packet. The OCR text was neither emitted nor
saved. The Qwen model call itself was stubbed; integrated live-profile behavior
and CPU cost remain unverified. The launcher keeps OCR opt-in; Qwen profiles must
pass `--screen-ocr` for the adapter to enable it. UIA remains a separate source.
