"""Acceptance test for canonical JAWL memory through the real Companion UI.

``write`` creates and revises a fixture, ``verify`` checks it after the whole
managed profile has been restarted, and ``all`` retains the native-agent check.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

FIRST_VALUE = "\u043f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442 \u0432\u0435\u0440\u0441\u0438\u0438 \u043e\u0434\u0438\u043d"
REVISED_VALUE = "\u043f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442 \u0432\u0435\u0440\u0441\u0438\u0438 \u0434\u0432\u0430"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--memory-key", default="acceptance.preference.ui_revision")
    parser.add_argument("--phase", choices=("all", "write", "verify"), default="all")
    parser.add_argument("--report", type=Path, default=Path("runtime/memory-ui-acceptance.json"))
    args = parser.parse_args()
    report = {"schema_version": 2, "profile": "memory_ui_acceptance", "phase": args.phase,
              "status": "failed", "checks": [], "failure": None}
    driver = None
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support.ui import Select, WebDriverWait

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1440,1000")
        driver = webdriver.Edge(options=options)
        driver.set_script_timeout(210)
        wait = WebDriverWait(driver, 30)
        driver.get(args.url.rstrip("/") + "/")
        wait.until(lambda d: d.find_element(By.ID, "send").is_displayed())
        driver.find_element(By.CSS_SELECTOR, '[data-tab="memory"]').click()
        wait.until(lambda d: d.find_element(By.ID, "jawl-memory-save").is_displayed())
        report["checks"].append("memory_ui_loaded")

        def set_search(value: str) -> None:
            driver.execute_script(
                "const e=document.querySelector('#jawl-memory-search'); e.value=arguments[0]; e.dispatchEvent(new Event('input',{bubbles:true}));",
                value,
            )

        def fill(value: str) -> None:
            for element_id, text_value in (("jawl-memory-key", args.memory_key),
                                            ("jawl-memory-source", "memory-ui-acceptance"),
                                            ("jawl-memory-value", value)):
                element = driver.find_element(By.ID, element_id)
                element.clear()
                element.send_keys(text_value)
            Select(driver.find_element(By.ID, "jawl-memory-kind")).select_by_value("preference")

        def editor_contains(value: str) -> bool:
            return value in driver.find_element(By.ID, "jawl-memory-editor").text

        def refresh_memory() -> None:
            driver.execute_async_script("""
              const done = arguments[arguments.length - 1];
              if (typeof refresh !== 'function') return done(false);
              Promise.resolve(refresh()).then(() => done(true)).catch(() => done(false));
            """)

        if args.phase in ("all", "write"):
            fill(FIRST_VALUE)
            driver.find_element(By.ID, "jawl-memory-save").click()
            wait.until(lambda d: args.memory_key in d.find_element(By.ID, "jawl-memory-editor").text)
            report["checks"].append("preference_created_through_ui")
            set_search(args.memory_key)
            wait.until(lambda d: args.memory_key in d.find_element(By.ID, "jawl-memory-editor").text)
            clicked = driver.execute_script(
                "const k=arguments[0], r=[...document.querySelectorAll('.memory-row')].find(e=>e.textContent.includes(k)); if(!r)return false; r.querySelector('button')?.click(); return true;",
                args.memory_key,
            )
            if not clicked:
                raise RuntimeError("memory row disappeared before edit click")
            value = driver.find_element(By.ID, "jawl-memory-value")
            value.clear()
            value.send_keys(REVISED_VALUE)
            driver.find_element(By.ID, "jawl-memory-save").click()
            wait.until(lambda d: editor_contains(REVISED_VALUE))
            report["checks"].append("preference_revised_through_ui")

        if args.phase == "write":
            report["fixture_retained"] = True
            report["status"] = "passed"
        elif args.phase == "verify":
            deadline = time.monotonic() + 90
            recalled = False
            while time.monotonic() < deadline:
                try:
                    set_search(args.memory_key)
                    refresh_memory()
                    if editor_contains(REVISED_VALUE):
                        recalled = True
                        break
                except Exception:
                    pass
                time.sleep(2)
            if not recalled:
                raise RuntimeError("revised preference was not recalled within 90s after full process restart")
            report["checks"].append("revised_preference_recalled_after_full_restart")
            report["status"] = "passed"
        else:
            restart = driver.execute_async_script("""
              const done=arguments[0]; fetch('/api/session').then(r=>r.json()).then(s=>
                fetch('/api/jawl/restart',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-CSRF':s.csrf_token},body:'{}'}))
              .then(r=>r.json()).then(done).catch(e=>done({error:String(e)}));
            """)
            if not restart or restart.get("error") or restart.get("ok") is not True:
                raise RuntimeError(f"native restart failed: {restart}")
            report["checks"].append("native_restart_succeeded")
            deadline = time.monotonic() + 220
            recalled = False
            while time.monotonic() < deadline:
                try:
                    time.sleep(3)
                    set_search(args.memory_key)
                    refresh_memory()
                    if editor_contains(REVISED_VALUE):
                        recalled = True
                        break
                except Exception:
                    pass
            if not recalled:
                raise RuntimeError("revised preference was not recalled within 220s after native restart")
            report["checks"].append("revised_preference_recalled_after_restart")
            report["status"] = "passed"
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}:{exc}"
    finally:
        if driver is not None:
            if args.phase != "write":
                try:
                    driver.execute_async_script("""
                      const key=arguments[0], done=arguments[arguments.length-1];
                      fetch('/api/session').then(r=>r.json()).then(s=>fetch('/api/jawl/memory',{method:'POST',headers:{'Content-Type':'application/json','X-Companion-CSRF':s.csrf_token},body:JSON.stringify({operation:'forget',memory_key:key,reason:'acceptance cleanup'})}))
                      .then(r=>r.json()).then(done).catch(e=>done({error:String(e)}));
                    """, args.memory_key)
                except Exception as cleanup_error:
                    report["cleanup_error"] = f"{type(cleanup_error).__name__}:{cleanup_error}"
            driver.quit()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
