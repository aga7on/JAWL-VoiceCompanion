"""Diagnostic script to understand YouTube playback behavior around 40-70s."""

import time
import psutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

url = "https://www.youtube.com/watch?v=GXe8XEFA9Pc"

opts = Options()
opts.add_argument("--autoplay-policy=no-user-gesture-required")
opts.add_argument("--start-maximized")
opts.add_argument("--no-first-run")
opts.add_argument("--no-default-browser-check")
opts.add_argument("--disable-search-engine-choice-screen")

print("Launching Chrome...")
driver = webdriver.Chrome(options=opts)
try:
    driver.get(url)
    time.sleep(3)

    js_init = """
    var v = document.querySelector('video');
    if (v) {
        v.currentTime = 40.0; // Seek directly to 40s to see what happens at 50s!
        v.muted = false;
        v.volume = 1.0;
        v.play();
        return {found: true, currentTime: v.currentTime, duration: v.duration, paused: v.paused};
    }
    return {found: false};
    """
    res = driver.execute_script(js_init)
    print("Init res:", res)

    for i in range(25):
        time.sleep(1.0)
        js_diag = """
        var v = document.querySelector('video');
        var ad = document.querySelector('.ad-showing, .ad-interrupting');
        var skipBtn = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-ad-overlay-close-button');
        var dialog = document.querySelector('yt-confirm-dialog-renderer, ytd-popup-container');
        return {
            videoFound: !!v,
            currentTime: v ? v.currentTime : null,
            paused: v ? v.paused : null,
            ended: v ? v.ended : null,
            adShowing: !!ad,
            skipBtn: !!skipBtn,
            dialogFound: !!dialog && dialog.offsetHeight > 0,
            url: window.location.href,
            title: document.title
        };
        """
        try:
            diag = driver.execute_script(js_diag)
            print(f"[{i:02d}s] Diag:", diag)
        except Exception as e:
            print(f"[{i:02d}s] Exception: {type(e).__name__}: {e}")

finally:
    driver.quit()
