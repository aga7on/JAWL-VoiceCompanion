"""Browser Orchestrator Probe for YouTube Video Sessions.

Tests launching Chrome in non-headless mode, navigating to video starting at 0s,
unmuting / autoplaying, and querying the HTML5 video element:
currentTime, duration, paused, ended, playbackRate.
"""

from __future__ import annotations

import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def test_browser_video_player(url: str, duration_sec: int = 5):
    opts = Options()
    opts.add_argument("--autoplay-policy=no-user-gesture-required")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-search-engine-choice-screen")

    print(f"Launching Chrome for: {url}")
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(url)
        time.sleep(3)

        # Ensure video is playing and not muted via JavaScript on HTML5 video element
        js_setup = """
        var v = document.querySelector('video');
        if (v) {
            v.muted = false;
            v.volume = 1.0;
            v.play();
            return {
                found: true,
                currentTime: v.currentTime,
                duration: v.duration,
                paused: v.paused,
                volume: v.volume,
                muted: v.muted
            };
        }
        return {found: false};
        """
        res = driver.execute_script(js_setup)
        print("Video element status:", res)

        time.sleep(duration_sec)

        js_query = """
        var v = document.querySelector('video');
        return v ? {
            currentTime: v.currentTime,
            duration: v.duration,
            paused: v.paused
        } : null;
        """
        status_after = driver.execute_script(js_query)
        print("Video status after playback:", status_after)
        return True
    finally:
        print("Closing browser driver...")
        driver.quit()


if __name__ == "__main__":
    # Test on Video 2 short probe
    url = "https://www.youtube.com/watch?v=YsupgLm_Pt4"
    test_browser_video_player(url, duration_sec=4)
