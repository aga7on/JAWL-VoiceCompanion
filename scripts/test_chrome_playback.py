from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

opts = Options()
opts.add_argument("--autoplay-policy=no-user-gesture-required")
opts.add_argument("--start-maximized")
opts.add_argument("--no-first-run")
opts.add_argument("--no-default-browser-check")

driver = webdriver.Chrome(options=opts)
url = "https://www.youtube.com/watch?v=GXe8XEFA9Pc"
driver.get(url)
time.sleep(3)

js = """
var v = document.querySelector('video');
if (v) {
    v.muted = false;
    v.volume = 1.0;
    v.currentTime = 5.0;
    var p = v.play();
    return {found: true, paused: v.paused, muted: v.muted, volume: v.volume, time: v.currentTime};
}
return {found: false};
"""
res = driver.execute_script(js)
print("JS result:", res)
time.sleep(5)
status = driver.execute_script("var v = document.querySelector('video'); return v ? {time: v.currentTime, paused: v.paused} : null;")
print("Status after 5s:", status)
driver.quit()
