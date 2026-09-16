"""A0: live browser acceptance of the U6 Settings panel against the live profile.

Assumes an already-running integrated profile (control on 2367). Drives the real
control panel in a headless browser, establishes a session, loads every Settings
card through the config hub, edits a key through the real save path, verifies the
hub readback and the profile file change, and restores the original value.

This is NOT the mock-brain interaction harness: it requires the live profile so
that hub writes touch the real profile config.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_CONFIG = ROOT / "runtime" / "instances" / "daily" / "config" / "settings.yaml"
REPORT = ROOT / "runtime" / "settings-browser-acceptance.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    report = {"schema_version": 1, "profile": "settings_browser_acceptance", "status": "failed", "checks": [], "failure": None}
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
        options.add_argument("--window-size=1600,1000")
        driver = webdriver.Edge(options=options)
        wait = WebDriverWait(driver, 20)

        driver.get(f"{args.url}/")
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-tab="settings"]').is_displayed())
        report["checks"].append("panel_loaded")

        # Establish a session (sets the companion_session cookie + csrf).
        session = driver.execute_async_script(
            "const done=arguments[0];fetch('/api/session',{method:'GET'}).then(r=>r.json()).then(j=>done(j)).catch(e=>done({error:String(e)}))"
        )
        assert session.get("csrf_token"), f"session handshake failed: {session}"
        report["checks"].append("session_established")

        # Open the Settings tab (triggers loadSettingsHub).
        driver.find_element(By.CSS_SELECTOR, '[data-tab="settings"]').click()
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-panel="settings"]').is_displayed())
        # Hub load is async; wait until the agent-name field is populated.
        wait.until(lambda d: d.find_element(By.ID, "cfg-agent-name").get_attribute("value") != "")
        report["checks"].append("settings_loaded")

        # Every settings card must render with at least one cfg input.
        card_ids = ["cfg-agent-name", "cfg-heartbeat", "cfg-vector-sim", "cfg-curi-rate"]
        for cid in card_ids:
            el = driver.find_element(By.ID, cid)
            assert el.is_displayed(), f"{cid} not visible"
        report["checks"].append("cards_rendered")

        # The hub must report a revision (proves the live profile is wired).
        revision = driver.execute_script("return typeof configRevision !== 'undefined' ? configRevision : null")
        assert revision, "no config revision from hub"
        report["checks"].append(f"hub_revision:{revision[:12]}")

        # Round-trip a safe scalar through the real save path: agent_name.
        original = driver.find_element(By.ID, "cfg-agent-name").get_attribute("value")
        sentinel = original + "-a0"
        driver.execute_script(
            "const el=document.getElementById('cfg-agent-name');"
            "el.value=arguments[0];el.dispatchEvent(new Event('input',{bubbles:true}));",
            sentinel,
        )
        # Install a one-shot error hook before clicking save, then call the
        # save handler directly so its async body is captured.
        driver.execute_script(
            "window.__lastSaveError=null;"
            "const orig=saveSettingsHub;"
            "window.__savePromise=Promise.resolve().then(()=>saveSettingsHub()).catch(e=>{window.__lastSaveError=String(e&&e.stack||e)});"
        )
        # Wait for the save to settle (status text changes or a JS error appears).
        deadline = time.time() + 20
        while time.time() < deadline:
            status_text = driver.find_element(By.ID, "settings-status").text
            js_err = driver.execute_script("return window.__lastSaveError")
            if js_err or "Сохранено" in status_text or "Конфликт" in status_text or "Ошибка" in status_text or "Нет изменений" in status_text:
                break
            time.sleep(0.3)
        status_text = driver.find_element(By.ID, "settings-status").text
        js_err = driver.execute_script("return window.__lastSaveError")
        report["save_status_text"] = status_text
        report["save_js_error"] = js_err
        assert "Сохранено" in status_text, f"unexpected save status: {status_text!r} js_error={js_err}"
        assert "Readback:" not in status_text, f"readback drift indicates non-idempotent save: {status_text!r}"
        report["checks"].append("settings_saved")

        # The profile file must now carry the sentinel (hub writes to disk).
        deadline = time.time() + 5
        body = ""
        while time.time() < deadline:
            body = PROFILE_CONFIG.read_text(encoding="utf-8")
            if sentinel in body:
                break
            time.sleep(0.3)
        assert sentinel in body, "profile settings.yaml not updated by hub save"
        report["checks"].append("profile_file_updated")

        # Restore the original value through the same path.
        driver.execute_script(
            "const el=document.getElementById('cfg-agent-name');"
            "el.value=arguments[0];el.dispatchEvent(new Event('input',{bubbles:true}));",
            original,
        )
        driver.find_element(By.ID, "settings-save").click()
        wait.until(lambda d: "Сохранено" in (d.find_element(By.ID, "settings-status").text or ""))
        report["checks"].append("settings_restored")

        # Shell rail reflects live status.
        rail = driver.find_element(By.ID, "shell-rail")
        wait.until(lambda d: d.find_element(By.ID, "shell-rail").text.strip() != "")
        report["checks"].append("shell_rail_live")

        report["status"] = "passed"
    except Exception as exc:  # keep an explicit failed artifact
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if driver is not None:
            try:
                shot = ROOT / "runtime" / "browser-evidence" / "settings-acceptance.png"
                shot.parent.mkdir(parents=True, exist_ok=True)
                driver.save_screenshot(str(shot))
                report["screenshot"] = str(shot)
            except Exception:
                pass
            driver.quit()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
