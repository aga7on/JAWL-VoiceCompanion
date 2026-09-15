"""Verify the real Live2D presentation surface in a browser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--screenshot", type=Path, default=Path("runtime/live2d-smoke.png"))
    parser.add_argument("--wait", type=float, default=5.0)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    report: dict[str, object] = {"schema_version": 1, "url": base, "status": "failed"}
    try:
        with urlopen(base + "/api/presentation/config", timeout=5) as response:
            config = json.loads(response.read().decode("utf-8"))
        report["config"] = {
            "ready": config.get("ready") is True,
            "model_url": config.get("model_url"),
            "runtime_url": config.get("runtime_url"),
        }
        if config.get("ready") is not True:
            raise RuntimeError("presentation config is not Live2D-ready")
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=900,700")
        driver = webdriver.Edge(options=options)
        try:
            driver.get(base + "/avatar?debug=1")
            driver.implicitly_wait(1)
            import time

            time.sleep(args.wait)
            state = driver.execute_script(
                "return {hidden:document.querySelector('#live2d-canvas')?.classList.contains('hidden'),"
                "debug:document.querySelector('#debug')?.textContent || '',"
                "width:document.querySelector('#live2d-canvas')?.width || 0};"
            )
            report["browser"] = state
            debug = str(state.get("debug", ""))
            if state.get("hidden") is True or "Live2D e:on m:on l:on" not in debug:
                raise RuntimeError(f"Live2D renderer not active: {debug}")
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            driver.save_screenshot(str(args.screenshot))
            report["screenshot"] = str(args.screenshot)
        finally:
            driver.quit()
        report["status"] = "passed"
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
