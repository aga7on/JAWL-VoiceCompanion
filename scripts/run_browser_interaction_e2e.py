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
        from selenium import webdriver
        from selenium.webdriver.common.by import By
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
        driver.get(f"http://127.0.0.1:{port}/")
        wait = WebDriverWait(driver, 15)
        wait.until(lambda d: d.find_element(By.ID, "send").is_displayed())
        report["checks"].append("control_loaded")
        box = driver.find_element(By.ID, "input")
        box.send_keys("/help")
        driver.find_element(By.ID, "send").click()
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "#messages .message")) >= 1)
        box.send_keys("/tab voice")
        driver.find_element(By.ID, "send").click()
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-panel="voice"]').is_displayed())
        driver.find_element(By.CSS_SELECTOR, '[data-tab="home"]').click()
        report["checks"].append("local_slash_commands")
        gate = driver.find_element(By.ID, "mic-gate")
        driver.execute_script("arguments[0].value='0.075'; arguments[0].dispatchEvent(new Event('input', {bubbles:true})); arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", gate)
        wait.until(lambda d: d.execute_script("return localStorage.getItem('jawl-mic-gate')") == "0.075")
        report["checks"].append("gate_persisted")
        box = driver.find_element(By.ID, "input")
        box.send_keys("Проверь связь")
        driver.find_element(By.ID, "send").click()
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "#messages .message")) >= 2)
        report["checks"].append("chat_interaction")
        assert not driver.find_element(By.ID, "companion-signal").get_attribute("class").endswith("active"), "text must not light speech lamp"
        audio_started = driver.execute_async_script("""
          const done = arguments[0];
          startAvatarStreamMonitor().then(monitor => {
            if (!monitor) return done(false);
            const buffer = avatarAudioContext.createBuffer(1, 48000, 48000);
            const samples = buffer.getChannelData(0);
            for (let i = 0; i < 24000; i++) samples[i] = .2 * Math.sin(i * 2 * Math.PI * 440 / 48000);
            speechSession = {monitor, controller: new AbortController(), nextStart: avatarAudioContext.currentTime};
            scheduleSpeechAudio(speechSession, buffer);
            monitor.streamDone = true;
            done(true);
          }).catch(() => done(false));
        """)
        assert audio_started, "audio monitor unavailable"
        wait.until(lambda d: "active" in d.find_element(By.ID, "companion-signal").get_attribute("class").split())
        wait.until(lambda d: "active" not in d.find_element(By.ID, "companion-signal").get_attribute("class").split())
        driver.execute_script("stopAvatarAudioMonitor()")
        report["checks"].append("synthetic_audio_lamp_tone_silence")
        screenshot = args.evidence_dir / "browser-interaction-control.png"
        driver.save_screenshot(str(screenshot))
        report["screenshots"].append(str(screenshot))
        report["viewports"] = []
        for width, height in [(1920, 1080), (1280, 720), (1024, 768), (768, 1024), (390, 844), (320, 740)]:
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1,
                "mobile": width < 700,
            })
            for tab in ["home", "voice", "perception", "memory", "access", "system"]:
                driver.find_element(By.CSS_SELECTOR, f'[data-tab="{tab}"]').click()
                wait.until(lambda d: d.find_element(By.CSS_SELECTOR, f'[data-panel="{tab}"]').is_displayed())
                dimensions = driver.execute_script("return {width: innerWidth, content: document.documentElement.scrollWidth}")
                assert dimensions["content"] <= dimensions["width"] + 1, (width, tab, dimensions)
            driver.find_element(By.CSS_SELECTOR, '[data-tab="home"]').click()
            driver.execute_script("window.scrollTo(0, 0)")
            screenshot = args.evidence_dir / f"control-{width}x{height}.png"
            driver.save_screenshot(str(screenshot))
            report["screenshots"].append(str(screenshot))
            if width < 700:
                send = driver.find_element(By.ID, "send")
                assert driver.execute_script("return arguments[0].getBoundingClientRect().bottom <= innerHeight", send), (width, "composer below fold")
            report["viewports"].append({"width": width, "height": height, "all_tabs_no_overflow": True})
        report["checks"].append("responsive_all_tabs_six_viewports")
        report["status"] = "passed"
    except Exception as exc:  # keep an explicit failed/skipped artifact
        report["failure"] = f"{type(exc).__name__}: {exc}"
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
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
