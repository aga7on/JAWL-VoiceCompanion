"""Benchmark transient visual event detection (100ms - 200ms) with IncrementalSpatialMatrix."""

from __future__ import annotations

import time
import numpy as np
from jawl_voicecompanion.visual_stream import IncrementalSpatialMatrix

def test_transient_events():
    matrix = IncrementalSpatialMatrix(grid_shape=(21, 30), keyframe_interval=120, tile_delta_threshold=0.03)
    
    # Base background (desktop / game frame)
    rng = np.random.RandomState(42)
    base_frame = rng.randint(40, 80, size=(1080, 1920, 3), dtype=np.uint8)
    
    # Prime matrix
    matrix.update(base_frame, commit=True)
    
    # We simulate a 30 FPS visual stream (33.3 ms per frame)
    # Event 1: Enemy / flash appears in top-right for 100ms (3 frames at 30 FPS)
    # Event 2: Item pickup in center for 200ms (6 frames at 30 FPS)
    
    fps = 30
    frame_dt = 1.0 / fps
    total_duration_sec = 2.0
    total_frames = int(total_duration_sec * fps)
    
    events_detected = []
    times = []
    
    print(f"Running transient event benchmark at {fps} FPS (dt={frame_dt*1000:.1f}ms)...")
    
    t_start = time.perf_counter()
    for frame_idx in range(total_frames):
        t_frame = frame_idx * frame_dt
        frame = base_frame.copy()
        
        # Inject Event 1: 100ms transient target (frames 15 to 17: 0.500s to 0.600s)
        if 15 <= frame_idx <= 17:
            # 100x100 box in top-right
            frame[50:180, 1500:1650] = 240
            
        # Inject Event 2: 200ms transient target (frames 35 to 40: 1.167s to 1.333s)
        if 35 <= frame_idx <= 40:
            # 200x200 box in center
            frame[440:640, 860:1060] = 220
            
        t0 = time.perf_counter()
        changed, dirty, bbox = matrix.update(frame, commit=True)
        t_step = (time.perf_counter() - t0) * 1000.0
        times.append(t_step)
        
        if changed and dirty > 0 and dirty < 630: # partial update
            events_detected.append((frame_idx, t_frame, dirty, bbox))
            
    print(f"\nProcessing time per tick: min={min(times):.3f}ms, p50={np.median(times):.3f}ms, max={max(times):.3f}ms")
    print(f"Detected {len(events_detected)} transient change ticks:")
    for f_idx, t_f, d, bbox in events_detected:
        print(f"  Frame {f_idx:02d} ({t_f*1000:.0f}ms): dirty_tiles={d}, bbox={bbox}")
        
    # Verify Event 1 (100ms) - Onset and Offset detection
    ev1_ticks = [e for e in events_detected if 15 <= e[0] <= 18]
    print(f"\n100ms Event (frames 15-18): detected onset (frame {ev1_ticks[0][0]}) and offset (frame {ev1_ticks[1][0] if len(ev1_ticks)>1 else 'N/A'}). BBox: {ev1_ticks[0][3] if ev1_ticks else 'None'}")
    assert len(ev1_ticks) == 2, f"Expected onset + offset (2 ticks) for 100ms event, got {len(ev1_ticks)}"
    assert ev1_ticks[0][0] == 15, "Onset should be detected at frame 15 (onset of transient target)"
    assert ev1_ticks[1][0] == 18, "Offset should be detected at frame 18 (vanishing of transient target)"

    # Verify Event 2 (200ms) - Onset and Offset detection
    ev2_ticks = [e for e in events_detected if 35 <= e[0] <= 41]
    print(f"200ms Event (frames 35-41): detected onset (frame {ev2_ticks[0][0]}) and offset (frame {ev2_ticks[1][0] if len(ev2_ticks)>1 else 'N/A'}). BBox: {ev2_ticks[0][3] if ev2_ticks else 'None'}")
    assert len(ev2_ticks) == 2, f"Expected onset + offset (2 ticks) for 200ms event, got {len(ev2_ticks)}"
    assert ev2_ticks[0][0] == 35, "Onset should be detected at frame 35"
    assert ev2_ticks[1][0] == 41, "Offset should be detected at frame 41"
    
    print("\n>>> TRANSIENT EVENT DETECTION (100ms - 200ms) AT 30 FPS: PASS!")

if __name__ == "__main__":
    test_transient_events()
