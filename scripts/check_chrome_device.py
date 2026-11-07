from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from pycaw.pycaw import AudioUtilities
from comtypes import CoInitialize, CoUninitialize
import time

opts = Options()
opts.add_argument("--autoplay-policy=no-user-gesture-required")
opts.add_argument("--start-maximized")

driver = webdriver.Chrome(options=opts)
driver.get("https://www.youtube.com/watch?v=GXe8XEFA9Pc")
time.sleep(3)

driver.execute_script("""
var v = document.querySelector('video');
if (v) {
    v.muted = false;
    v.volume = 1.0;
    v.play();
}
""")
time.sleep(2)

CoInitialize()
sessions = AudioUtilities.GetAllSessions()
print(f"Total audio sessions while Chrome is playing: {len(sessions)}")
for s in sessions:
    proc = s.Process
    name = proc.name() if proc else "System"
    vol = s.SimpleAudioVolume.GetMasterVolume() if s.SimpleAudioVolume else None
    print(f"  Session: {name} (PID: {s.ProcessId}) | Volume: {vol}")
CoUninitialize()

driver.quit()
