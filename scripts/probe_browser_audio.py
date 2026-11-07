from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import pyaudiowpatch as pyaudio
import numpy as np
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
    v.currentTime = 30.0; // Seek to middle where music and dialogue are active
    v.play();
}
"""
driver.execute_script(js)
time.sleep(2)

p = pyaudio.PyAudio()
for dev_id in [34, 35, 36, 37, 38, 39, 40]:
    info = p.get_device_info_by_index(dev_id)
    name = info.get("name")
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=int(info.get("maxInputChannels", 2)),
            rate=int(info.get("defaultSampleRate", 48000)),
            input=True,
            input_device_index=dev_id,
            frames_per_buffer=2048,
        )
        # Read a few chunks
        chunks = []
        for _ in range(5):
            chunks.append(stream.read(2048, exception_on_overflow=False))
        stream.stop_stream()
        stream.close()
        raw = b"".join(chunks)
        arr = np.frombuffer(raw, dtype=np.int16)
        peak = float(np.max(np.abs(arr)))
        rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) / 32768.0
        print(f"Device [{dev_id}] {name}: peak={peak}, rms={rms:.6f}")
    except Exception as e:
        print(f"Device [{dev_id}] {name}: Error {e}")

p.terminate()
driver.quit()
