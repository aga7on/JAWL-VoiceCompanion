"""Run real browser DOM interactions against an isolated Companion instance.

This deliberately uses the deterministic mock brain: it proves browser event
handling, gate controls, chat rendering, screenshot capture and teardown. It
does not claim live JAWL/LLM acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("runtime/browser-interaction-e2e.json"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("runtime/browser-evidence/interaction"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.report = (root / args.report).resolve() if not args.report.is_absolute() else args.report
    args.evidence_dir = (root / args.evidence_dir).resolve() if not args.evidence_dir.is_absolute() else args.evidence_dir
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    process = subprocess.Popen(
        [sys.executable, "-m", "jawl_voicecompanion", "--host", "127.0.0.1", "--port", str(port),
         "--presentation-host", "127.0.0.1", "--presentation-port", str(free_port())],
        cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    report = {"schema_version": 1, "profile": "browser_interaction_e2e", "status": "failed", "mode": "mock_brain", "checks": [], "screenshots": [], "failure": None}
    driver = None
    try:
        # The server can take a moment to compose its local runtime. A free
        # ephemeral port does not mean the child has bound it yet.
        ready_deadline = time.monotonic() + 20
        last_startup_error = None
        while time.monotonic() < ready_deadline:
            exit_code = process.poll()
            if exit_code is not None:
                stdout = process.stdout.read(8192).decode("utf-8", errors="replace") if process.stdout else ""
                stderr = process.stderr.read(8192).decode("utf-8", errors="replace") if process.stderr else ""
                raise RuntimeError(f"companion child exited {exit_code}; stdout={stdout[-2000:]}; stderr={stderr[-2000:]}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/app", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError) as exc:
                last_startup_error = str(exc)
            time.sleep(0.1)
        else:
            raise TimeoutError(f"companion /app did not become ready: {last_startup_error or 'timeout'}")

        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1440,1000")
        options.add_argument("--autoplay-policy=no-user-gesture-required")
        driver = webdriver.Edge(options=options)
        driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        # ADR-046 removed the legacy two-window shell. Exercise the current
        # single-window companion UI served at /app.
        driver.get(f"http://127.0.0.1:{port}/app")
        wait = WebDriverWait(driver, 15)
        wait.until(lambda d: d.find_element(By.ID, "chat-send").is_displayed())
        report["checks"].append("control_loaded")
        undersized = driver.execute_script("""
          return [...document.querySelectorAll('button:not([disabled]), input:not([type=hidden]), select, textarea, [role="button"]')]
            .filter(node => {
              const rect = node.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0 && (rect.width < 24 || rect.height < 24);
            })
            .map(node => ({label: node.getAttribute('aria-label') || node.textContent.trim(),
              width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height}));
        """)
        assert not undersized, ("visible controls below WCAG 2.2 24x24 CSS px minimum", undersized)
        report["checks"].append("visible_controls_meet_wcag22_min_target_size")
        box = driver.find_element(By.ID, "chat-input")
        box.send_keys("/help")
        box.send_keys(Keys.TAB)
        active = driver.switch_to.active_element
        assert active.get_attribute("id") == "chat-send", "Tab must move from message input to send button"
        focus = driver.execute_script("""
          const node = document.activeElement, style = getComputedStyle(node);
          return {visible: node.matches(':focus-visible'), outline: style.outlineStyle, width: parseFloat(style.outlineWidth)};
        """)
        assert focus["visible"] and focus["outline"] != "none" and focus["width"] >= 2, ("keyboard focus ring missing", focus)
        active.send_keys(Keys.ENTER)
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "#chat-log .msg")) >= 2)
        # The current single-window UI uses rail tabs and data-section panels.
        driver.execute_script("""
          const originalFetch = window.fetch.bind(window);
          window.fetch = (input, init = {}) => {
            const url = typeof input === 'string' ? input : input.url;
            if (String(url) === '/api/config-hub') {
              return Promise.resolve(new Response(JSON.stringify({
                ok: true, revision: 'ux-e2e-r1', values: {
                  'settings:system.proactive_guidance': false,
                  'settings:llm.temperature': 0.4
                }
              }), {status: 200, headers: {'Content-Type': 'application/json'}}));
            }
            return originalFetch(input, init);
          };
        """)
        driver.find_element(By.CSS_SELECTOR, '[data-tab="settings"]').send_keys(Keys.ENTER)
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-section="settings"]').is_displayed())
        switch = wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-section="settings"] [role="switch"]'))
        assert switch.tag_name == 'button' and switch.get_attribute('aria-label') == 'Проактивные подсказки'
        switch.send_keys(Keys.SPACE)
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-section="settings"] [role="switch"]').get_attribute('aria-checked') == 'true')
        report["checks"].append("settings_switch_has_name_and_keyboard_activation")
        driver.find_element(By.CSS_SELECTOR, '[data-tab="voice"]').send_keys(Keys.ENTER)
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-section="voice"]').is_displayed())
        wait.until(lambda d: d.find_element(By.ID, "mic-select").is_displayed())
        report["checks"].append("local_slash_commands")
        assert driver.find_element(By.ID, "asr-status").is_displayed(), "ASR status unavailable"
        report["checks"].append("voice_settings_available")
        driver.find_element(By.CSS_SELECTOR, '[data-tab="chat"]').click()
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-section="chat"]').is_displayed())
        box = driver.find_element(By.ID, "chat-input")
        box.send_keys("Проверь связь")
        driver.find_element(By.ID, "chat-send").click()
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "#chat-log .msg")) >= 4)
        report["checks"].append("chat_interaction")
        assert "Проверь связь" in driver.find_element(By.ID, "chat-log").text
        driver.execute_script("""
          window.__dndRequests = [];
          const originalFetch = window.fetch.bind(window);
          window.fetch = (input, init = {}) => {
            const url = typeof input === 'string' ? input : input.url;
            if (String(url).startsWith('/api/')) {
              window.__dndRequests.push({url: String(url), method: String(init.method || 'GET').toUpperCase()});
            }
            return originalFetch(input, init);
          };
        """)
        driver.find_element(By.ID, "toggle-compact").click()
        dnd = wait.until(lambda d: d.find_element(By.ID, "hud-dnd") if d.find_element(By.ID, "hud-dnd").is_displayed() else False)
        dnd.send_keys(Keys.SPACE)
        wait.until(lambda d: any(
            item["url"].startswith("/api/attention") and item["method"] == "POST"
            for item in d.execute_script("return window.__dndRequests")
        ))
        dnd.send_keys(Keys.ENTER)  # restore the default state for the remaining UI checks
        wait.until(lambda d: len([
            item for item in d.execute_script("return window.__dndRequests")
            if item["url"].startswith("/api/attention") and item["method"] == "POST"
        ]) >= 2)
        assert not any(
            item["url"].startswith(("/api/ambient-audio/", "/api/ambient-memory/"))
            and item["url"].rsplit("/", 1)[-1] in {"pause", "resume"}
            for item in driver.execute_script("return window.__dndRequests")
        ), "DND must not pause or resume sensory capture"
        compact_undersized = driver.execute_script("""
          return [...document.querySelectorAll('.hud-dock button:not([disabled])')]
            .filter(node => {
              const rect = node.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0 && (rect.width < 24 || rect.height < 24);
            })
            .map(node => ({label: node.getAttribute('aria-label'),
              width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height}));
        """)
        assert not compact_undersized, ("compact HUD controls below 24x24 CSS px", compact_undersized)
        report["checks"].append("compact_hud_controls_meet_wcag22_min_target_size")
        driver.find_element(By.ID, "hud-expand").click()
        wait.until(lambda d: d.find_element(By.ID, "toggle-compact").is_displayed())
        report["checks"].append("dnd_only_controls_initiative")
        report["checks"].append("keyboard_tab_focus_enter_activation")
        screenshot = args.evidence_dir / "browser-interaction-control.png"
        driver.save_screenshot(str(screenshot))
        report["screenshots"].append(str(screenshot))
        report["viewports"] = []
        for width, height in [
            (1920, 1080), (1280, 720), (1024, 768), (768, 1024), (720, 480),
            (390, 844), (360, 540), (320, 740), (320, 420),
        ]:
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1,
                "mobile": width < 700,
            })
            for tab in ["chat", "avatar", "voice", "memory", "settings", "system"]:
                driver.find_element(By.CSS_SELECTOR, f'[data-tab="{tab}"]').click()
                wait.until(lambda d: d.find_element(By.CSS_SELECTOR, f'[data-section="{tab}"]').is_displayed())
                dimensions = driver.execute_script("return {width: innerWidth, content: document.documentElement.scrollWidth}")
                assert dimensions["content"] <= dimensions["width"] + 1, (width, tab, dimensions)
                if (width, height) in {(1280, 720), (360, 540)}:
                    screenshot = args.evidence_dir / f"section-{tab}-{width}x{height}.png"
                    driver.save_screenshot(str(screenshot))
                    report["screenshots"].append(str(screenshot))
                if tab == "settings" and width <= 400:
                    toolbar_layout = driver.execute_script("""
                      const card = document.querySelector('.settings-toolbar').getBoundingClientRect();
                      const heading = document.querySelector('.settings-heading').getBoundingClientRect();
                      const search = document.querySelector('#settings-search').getBoundingClientRect();
                      return {cardWidth: card.width, searchWidth: search.width,
                        headingBottom: heading.bottom, searchTop: search.top};
                    """)
                    assert toolbar_layout["searchWidth"] >= toolbar_layout["cardWidth"] * 0.8, (width, "settings search is too narrow", toolbar_layout)
                    assert toolbar_layout["searchTop"] >= toolbar_layout["headingBottom"] - 1, (width, "settings search does not stack below its heading", toolbar_layout)
                    if width == 360:
                        report["settings_toolbar_layout"] = toolbar_layout
                if tab == "avatar":
                    model_labels = driver.execute_script("""
                      return [...document.querySelectorAll('.model-tile')].map(node => ({
                        visible: node.innerText.replace(/\\s+/g, ' ').trim(),
                        accessible: node.getAttribute('aria-label') || ''
                      })).filter(row => !row.visible || !row.accessible.includes(row.visible));
                    """)
                    assert not model_labels, (width, "wardrobe button name omits visible text", model_labels)
                    if width == 1280:
                        report["checks"].append("wardrobe_names_include_visible_model_and_size")
                if tab == "system":
                    # Exercise the long real NVIDIA loopback label at compact
                    # widths; the mock server has no hardware endpoint attached.
                    driver.execute_script("""
                      const node = document.querySelector('#sensor-loopback-device');
                      node.textContent = '\u0423\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u043e: DigitalOutput (2- NVIDIA High Definition Audio) [Loopback] \u00b7 WASAPI 2 / 38 \u00b7 48 \u043a\u0413\u0446 \u00b7 2 \u043a\u0430\u043d\u0430\u043b\u0430';
                    """)
                    device_layout = driver.execute_script("""
                      const node = document.querySelector('#sensor-loopback-device');
                      const rect = node.getBoundingClientRect();
                      return {right: rect.right, width: rect.width, scrollWidth: node.scrollWidth,
                        clientWidth: node.clientWidth, height: rect.height, text: node.textContent};
                    """)
                    assert device_layout["right"] <= width + 1, (width, "loopback label exceeds viewport", device_layout)
                    assert device_layout["scrollWidth"] <= device_layout["clientWidth"] + 1, (width, "loopback label clips internally", device_layout)
                    if width == 320 and height == 420:
                        driver.execute_script("document.querySelector('#sensor-loopback-device').scrollIntoView({block: 'center'})")
                        visible = driver.execute_script("""
                          const rect = document.querySelector('#sensor-loopback-device').getBoundingClientRect();
                          return rect.top >= 0 && rect.bottom <= innerHeight;
                        """)
                        assert visible, (width, height, "loopback label cannot be scrolled into view", device_layout)
                        screenshot = args.evidence_dir / "system-loopback-320x420.png"
                        driver.save_screenshot(str(screenshot))
                        report["screenshots"].append(str(screenshot))
                        report["loopback_label_layout"] = device_layout
                        report["loopback_label_scrollable"] = visible
                        report["checks"].append("nvidia_loopback_label_wraps_and_scrolls")
            driver.find_element(By.CSS_SELECTOR, '[data-tab="chat"]').click()
            driver.execute_script("window.scrollTo(0, 0)")
            status_layout = driver.execute_script("""
              const strip = document.querySelector('.status-strip');
              const stage = document.querySelector('.stage-wrap');
              const stripRect = strip.getBoundingClientRect();
              const stageRect = stage.getBoundingClientRect();
              return {
                stripOutsideStage: !stage.contains(strip),
                reservedBeforeStage: stripRect.bottom <= stageRect.top + 1,
                hasAvatarState: Boolean(document.querySelector('#avatar-status')?.textContent.trim()),
                hasSensorState: Boolean(document.querySelector('#sensory-health')?.textContent.trim()),
                compactSensorVisible: getComputedStyle(document.querySelector('#sensory-health-compact')).display !== 'none',
                compactSensorHasText: Boolean(document.querySelector('#sensory-health-compact')?.textContent.trim()),
                compactSensorState: document.querySelector('#sensory-health-compact')?.dataset.state,
                sensorState: document.querySelector('#sensory-health')?.dataset.state,
              };
            """)
            assert status_layout["stripOutsideStage"], (width, "status strip overlaps avatar stage", status_layout)
            assert status_layout["reservedBeforeStage"], (width, "status strip is not reserved above the stage", status_layout)
            assert status_layout["hasAvatarState"] and status_layout["hasSensorState"], (width, "status missing", status_layout)
            if width <= 400:
                assert status_layout["compactSensorVisible"] and status_layout["compactSensorHasText"], (width, "compact sensor status missing", status_layout)
                assert status_layout["compactSensorState"] == status_layout["sensorState"], (width, "compact and accessible sensor states diverge", status_layout)
            screenshot = args.evidence_dir / f"control-{width}x{height}.png"
            driver.save_screenshot(str(screenshot))
            report["screenshots"].append(str(screenshot))
            if (width, height) == (360, 540):
                report["checks"].append("all_sections_screenshotted_desktop_and_compact")
            if width < 700:
                send = driver.find_element(By.ID, "chat-send")
                assert driver.execute_script("return arguments[0].getBoundingClientRect().bottom <= innerHeight", send), (width, "composer below fold")
                input_layout = driver.execute_script("""
                  const input = document.querySelector('#chat-input');
                  const stage = document.querySelector('.stage-wrap');
                  const caption = document.querySelector('#avatar-caption');
                  const rect = input.getBoundingClientRect();
                  return {
                    placeholder: input.placeholder,
                    inputVisible: rect.bottom <= innerHeight,
                    inputWidth: rect.width,
                    stageHeight: stage.getBoundingClientRect().height,
                    captionVisible: getComputedStyle(caption).display !== 'none',
                  };
                """)
                assert input_layout["inputVisible"] and input_layout["inputWidth"] >= 100, (width, "chat input clipped or too narrow", input_layout)
                if width <= 400:
                    assert input_layout["placeholder"] == "Сообщение…", (width, "narrow placeholder should stay on one line", input_layout)
                    assert input_layout["stageHeight"] <= 201, (width, "compact avatar stage consumes too much height", input_layout)
                    assert not input_layout["captionVisible"], (width, "duplicate reply caption covers compact avatar", input_layout)
            report["viewports"].append({"width": width, "height": height, "all_tabs_no_overflow": True, "sensor_status_reserved": True})
        report["checks"].append("responsive_all_tabs_nine_viewports")
        report["checks"].append("sensor_status_reserved_outside_avatar_stage")
        report["status"] = "passed"
    except Exception as exc:  # keep an explicit failed/skipped artifact
        report["failure"] = f"{type(exc).__name__}: {exc}"
        if driver is not None:
            try:
                report["browser_diagnostics"] = driver.execute_script("""
                  return {url: location.href, title: document.title,
                    readyState: document.readyState,
                    body: (document.body?.innerText || '').slice(0, 4000),
                    chat: (document.querySelector('#chat-log')?.innerText || '').slice(0, 2000)};
                """)
            except Exception as diagnostic_error:
                report["browser_diagnostics_error"] = str(diagnostic_error)[:300]
    finally:
        if driver is not None:
            driver.quit()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # JSON escapes Unicode so this diagnostic also works in Windows CP1251 shells.
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
