import pyaudiowpatch as pyaudio
import numpy as np

p = pyaudio.PyAudio()
devices = [34, 35, 36, 37, 38, 39, 40]

for dev_id in devices:
    info = p.get_device_info_by_index(dev_id)
    name = info.get("name")
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=int(info.get("maxInputChannels", 2)),
            rate=int(info.get("defaultSampleRate", 48000)),
            input=True,
            input_device_index=dev_id,
            frames_per_buffer=1024,
        )
        data = stream.read(4096, exception_on_overflow=False)
        stream.stop_stream()
        stream.close()
        arr = np.frombuffer(data, dtype=np.int16)
        rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) / 32768.0
        print(f"Device [{dev_id}] {name} -> RMS: {rms:.6f}")
    except Exception as e:
        print(f"Device [{dev_id}] {name} -> Error: {e}")

p.terminate()
