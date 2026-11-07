import pyaudiowpatch as pyaudio

p = pyaudio.PyAudio()
print("WASAPI hostApi:", pyaudio.paWASAPI)
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d.get("hostApi") == p.get_host_api_info_by_type(pyaudio.paWASAPI).get("index"):
        name = d.get("name")
        out_ch = d.get("maxOutputChannels")
        in_ch = d.get("maxInputChannels")
        is_lb = d.get("isLoopbackDevice")
        print(f"[{i}] {name} | out={out_ch} in={in_ch} loopback={is_lb}")
p.terminate()
