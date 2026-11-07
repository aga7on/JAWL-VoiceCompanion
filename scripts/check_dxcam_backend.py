import dxcam
try:
    cam0 = dxcam.create(device_idx=0, output_idx=0, processor_backend="numpy", output_color="RGB")
    f0 = cam0.grab(new_frame_only=False)
    print("DXCAM device 0 output 0 shape:", f0.shape if f0 is not None else None, "mean:", f0.mean(axis=(0,1)).astype(int) if f0 is not None else None)
except Exception as e:
    print("cam0 error:", e)

# Check Device 1
try:
    cam1_dev = dxcam.create(device_idx=1, output_idx=0, processor_backend="numpy", output_color="RGB")
    f1 = cam1_dev.grab(new_frame_only=False)
    print("DXCAM device 1 output 0 shape:", f1.shape if f1 is not None else None, "mean:", f1.mean(axis=(0,1)).astype(int) if f1 is not None else None)
except Exception as e:
    print("cam1_dev error:", e)
