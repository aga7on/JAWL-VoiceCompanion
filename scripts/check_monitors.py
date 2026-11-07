import dxcam

outputs = dxcam.device_info()
print("DXCAM DEVICE INFO:")
print(outputs)

# Also check PIL ImageGrab displays
from PIL import ImageGrab
import numpy as np

img = ImageGrab.grab(all_screens=True)
print("PIL all_screens size:", img.size)

img0 = ImageGrab.grab(all_screens=False)
print("PIL primary screen size:", img0.size, "mean RGB:", np.array(img0).mean(axis=(0,1)).astype(int))
