from PIL import ImageGrab
import numpy as np

img = ImageGrab.grab(all_screens=True)
arr = np.array(img)
print("Full virtual screen shape:", arr.shape)

screen0 = arr[:, :1920, :]
screen1 = arr[:, 1920:, :]

print("Screen 0 mean RGB:", screen0.mean(axis=(0,1)).astype(int), "std RGB:", screen0.std(axis=(0,1)).round(1))
print("Screen 1 mean RGB:", screen1.mean(axis=(0,1)).astype(int), "std RGB:", screen1.std(axis=(0,1)).round(1))

# Check dxcam outputs on Device 0
import dxcam
try:
    cam0 = dxcam.create(device_idx=0, output_idx=0)
    f0 = cam0.grab(new_frame_only=False)
    print("DXCAM device 0 output 0 shape:", f0.shape if f0 is not None else None, "mean:", f0.mean(axis=(0,1)).astype(int) if f0 is not None else None)
except Exception as e:
    print("cam0 error:", e)

try:
    cam1 = dxcam.create(device_idx=0, output_idx=1)
    f1 = cam1.grab(new_frame_only=False)
    print("DXCAM device 0 output 1 shape:", f1.shape if f1 is not None else None, "mean:", f1.mean(axis=(0,1)).astype(int) if f1 is not None else None)
except Exception as e:
    print("cam1 error:", e)
