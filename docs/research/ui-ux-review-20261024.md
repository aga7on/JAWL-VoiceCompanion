# UI/UX review, 24 Oct 2026

## Scope and evidence

Reviewed the current single-window companion UI with an isolated mock-brain profile. Captured chat, avatar, voice, memory, settings, and system screens at nine viewport sizes from 320×420 to 1920×1080. Browser checks covered navigation, keyboard focus and activation, DND behavior, settings search, sensor status layout, and overflow. This is not a live Electron or screen-reader acceptance run.

The browser interaction report is `runtime/ux-audit-20261024/report-verified.json`; rendered evidence is under `runtime/ux-audit-20261024/screens-verified/`.

## Scores

| Dimension | Score | Evidence and limit |
| --- | ---: | --- |
| Visual hierarchy | 7/10 | Avatar is the primary visual anchor; settings and system screens remain readable card-and-row layouts. The mock chat includes service-error copy, so it does not represent a healthy live session. |
| Consistency | 8/10 | Shared surfaces, spacing, and control styles; settings headings were made consistently Russian. |
| Accessibility | 8/10 | Keyboard focus and switch activation pass in the browser; rendered controls expose accessible names. Measured core text contrast is 6.14:1 to 15.36:1. A screen-reader audit was not run, so this is not a WCAG conformance claim. |
| Usability | 7/10 | Sensor states and primary chat actions are visible. Settings load failure now has a localized recovery action. Real service faults and tray operation still need live acceptance. |
| Responsiveness | 8/10 | All six sections passed horizontal-overflow checks at nine viewport sizes; long NVIDIA device text remains scrollable at 320×420. |
| Performance | 6/10 | No layout or interaction failures appeared in the mock browser run. Renderer frame rate, long-session memory, and real-model latency were not profiled. |

Weighted heuristic score: **7.4/10**. This describes the tested UI slice only.

## Changes made

- Settings toggles are native buttons with switch semantics, focusability, and keyboard activation.
- Generated settings fields receive accessible names; temperature slider and numeric input are distinguished.
- Settings-load failure is localized, announced as an alert, and offers a retry button.
- Settings group headings use consistent Russian labels.
- Desktop sensor status text increased from 10px to 11px; narrow layouts retain the denser 10px treatment.
- The top-bar compact-mode button now has a 24px minimum target height; the browser E2E checks visible controls in full and compact HUD modes against WCAG 2.2's 24×24 CSS-pixel target-size floor.

## Verification

- Settings regression and accessibility tests: **8/8 passed**.
- Browser interaction E2E: **passed**, including `settings_switch_has_name_and_keyboard_activation`, all six sections, and nine viewport sizes.
- Follow-up rendered target-size gate: **passed**, including full-window controls and all visible compact HUD buttons; report: `runtime/a11y-followup-20261024/report-target-size.json`.
- Scoped `git diff --check`: passed.
- Core foreground/background pairs measured in the active palette: muted text on card 6.14:1, muted text on background 6.97:1, primary text on background 15.36:1, accent on card 8.49:1. This is a limited sample, not a complete contrast audit.

## Remaining UX acceptance

The current browser run uses a mock brain and does not verify the live Electron tray, actual screen/audio device state, screen-reader output, or renderer performance over time. Validate those during the already-open integrated 30–60-minute companion run. The screenshot currently shows mock-only TTS/config service failures and must not be interpreted as a healthy live profile.

## 25 Oct follow-up

The service card note was clarified: it now says that process/port details are hidden and that service states are displayed in the panel. This removes the inaccurate implication that every service is healthy when the adjacent status rows show an unavailable service. Focused accessibility checks passed 4/4; browser interaction E2E passed across nine viewports, and the updated System screenshot was visually inspected. Evidence: `runtime/qwen-ui-browser-check-20261025-v2.json` and `runtime/qwen-ui-browser-check-20261025-v2/screens/section-system-1280x720.png`. This is still a mock-brain run, not live Qwen/Electron acceptance.
