from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from jawl_voicecompanion.process_loopback import ProcessLoopbackBridge
import psutil
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
    v.currentTime = 25.0;
    v.play();
}
""")
time.sleep(2)

# Find chrome process that uses CPU
chrome_procs = [p for p in psutil.process_iter(['pid', 'name']) if 'chrome' in p.info['name'].lower()]
print(f"Found {len(chrome_procs)} chrome processes")

# Bridge
bridge = ProcessLoopbackBridge()
captured_chunks = []

def on_pcm(data, rate, ch):
    captured_chunks.append(len(data))

# Try chrome root or service process
root_pid = driver.service.process.pid
# Chrome children
driver_proc = psutil.Process(root_pid)
children = driver_proc.children(recursive=True)
print(f"Driver PID: {root_pid}, Children: {[c.pid for c in children]}")

target_pid = children[0].pid if children else root_pid
print(f"Starting ProcessLoopbackBridge on PID {target_pid}...")
try:
    state = bridge.start(target_pid, consumer=on_pcm)
    print("Bridge started:", state)
    time.sleep(4)
    bridge.stop()
    print(f"Captured {len(captured_chunks)} chunks! Total bytes: {sum(captured_chunks)}")
except Exception as e:
    print("ProcessLoopbackBridge error:", e)

driver.quit()
