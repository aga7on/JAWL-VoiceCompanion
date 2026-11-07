"""Physical experimental verification of Kernel + Vector Vision Hypotheses.

Tests:
1. AVX2 / SIMD SQ8 Quantized Dot Product vs FP32 for 768-dim embeddings
2. LanceDB Process-Scoped Vector Indexing (Win32 PID/Window filtering)
3. Patch-Token Caching via Kernel DirtyRect simulation
4. Real DXGI Live Frame Angular Velocity in Embedding Space
"""

from __future__ import annotations

import time
import tempfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import lancedb
from jawl_voicecompanion.visual_stream import DXGIScreenCapture

# -------------------------------------------------------------------
# Experiment 1: Vector Quantization (SQ8 vs FP32 Dot Product)
# -------------------------------------------------------------------
def benchmark_vector_quantization():
    dim = 768
    num_vectors = 1000
    # Simulate 1000 historical keyframe embeddings
    db_vectors = np.random.randn(num_vectors, dim).astype(np.float32)
    db_vectors /= np.linalg.norm(db_vectors, axis=1, keepdims=True)

    query = np.random.randn(dim).astype(np.float32)
    query /= np.linalg.norm(query)

    # 1. FP32 Matrix Multiplication
    t0 = time.perf_counter()
    for _ in range(100):
        sims_fp32 = np.dot(db_vectors, query)
    t_fp32 = (time.perf_counter() - t0) / 100 * 1000

    # 2. SQ8 (Scalar Quantization to int8 [-127, 127])
    # Quantize: scale to 127
    db_sq8 = np.clip(np.round(db_vectors * 127.0), -127, 127).astype(np.int8)
    query_sq8 = np.clip(np.round(query * 127.0), -127, 127).astype(np.int8)

    t1 = time.perf_counter()
    for _ in range(100):
        # int8 dot product into int32 accumulator
        sims_sq8 = np.dot(db_sq8.astype(np.int32), query_sq8.astype(np.int32))
    t_sq8 = (time.perf_counter() - t1) / 100 * 1000

    # Accuracy / Cosine Fidelity correlation
    top10_fp32 = np.argsort(-sims_fp32)[:10]
    top10_sq8 = np.argsort(-sims_sq8)[:10]
    overlap = len(set(top10_fp32).intersection(set(top10_sq8)))

    memory_fp32_kb = db_vectors.nbytes / 1024
    memory_sq8_kb = db_sq8.nbytes / 1024

    return {
        "t_fp32_ms": t_fp32,
        "t_sq8_ms": t_sq8,
        "mem_fp32_kb": memory_fp32_kb,
        "mem_sq8_kb": memory_sq8_kb,
        "top10_overlap": overlap,
    }


# -------------------------------------------------------------------
# Experiment 2: LanceDB Kernel Process-Scoped Vector Search
# -------------------------------------------------------------------
def benchmark_lancedb_kernel_metadata_filtering():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)
        dim = 768
        n_rows = 2000

        # Create synthetic vectors with kernel metadata: PID, window title, extended bounds
        pids = [1001, 1002, 2048, 4096, 8192]
        records = []
        for i in range(n_rows):
            pid = pids[i % len(pids)]
            vec = np.random.randn(dim).astype(np.float32)
            vec /= np.linalg.norm(vec)
            records.append({
                "vector": vec.tolist(),
                "scene_id": f"scene_{i}",
                "pid": pid,
                "window_title": f"Process_{pid}_Window",
                "bbox_x": (i * 10) % 1920,
                "bbox_y": (i * 10) % 1080,
            })

        tbl = db.create_table("kernel_visual_memory", data=records)

        q_vec = np.random.randn(dim).astype(np.float32).tolist()

        # Unfiltered Search
        t0 = time.perf_counter()
        for _ in range(50):
            res_all = tbl.search(q_vec).limit(5).to_list()
        t_unfiltered = (time.perf_counter() - t0) / 50 * 1000

        # Kernel Process Filtered Search (Scoped to current foreground PID)
        target_pid = 2048
        t1 = time.perf_counter()
        for _ in range(50):
            res_filtered = tbl.search(q_vec).where(f"pid = {target_pid}").limit(5).to_list()
        t_filtered = (time.perf_counter() - t1) / 50 * 1000

        return {
            "t_unfiltered_ms": t_unfiltered,
            "t_filtered_ms": t_filtered,
            "filtered_pids": [r["pid"] for r in res_filtered],
        }


# -------------------------------------------------------------------
# Experiment 3: ViT Patch Token Caching via Kernel DirtyRects
# -------------------------------------------------------------------
def benchmark_patch_token_caching():
    # Standard ViT: 16x16 grid of patches = 256 patches
    grid_w, grid_h = 16, 16
    total_patches = grid_w * grid_h

    # Assume a local UI change (e.g. dialog box) affects a dirty rect of 4x3 patches = 12 patches
    dirty_patches = 12

    # Measure compute savings:
    patch_dim = 768
    # Dense full patch projection (256 patches * 768-dim linear layer)
    patch_pixels = 16 * 16 * 3  # 768 floats per patch
    weights = np.random.randn(patch_pixels, patch_dim).astype(np.float32)
    full_patches = np.random.randn(total_patches, patch_pixels).astype(np.float32)

    t0 = time.perf_counter()
    for _ in range(100):
        full_tokens = np.dot(full_patches, weights)
    t_full = (time.perf_counter() - t0) / 100 * 1000

    # Sparse update: only compute dirty patches and update token array in-place
    dirty_data = np.random.randn(dirty_patches, patch_pixels).astype(np.float32)
    t1 = time.perf_counter()
    for _ in range(100):
        dirty_tokens = np.dot(dirty_data, weights)
        full_tokens[:dirty_patches] = dirty_tokens
    t_sparse = (time.perf_counter() - t1) / 100 * 1000

    return {
        "t_full_ms": t_full,
        "t_sparse_ms": t_sparse,
        "speedup": t_full / max(0.0001, t_sparse),
        "computation_saved_pct": (1.0 - dirty_patches / total_patches) * 100,
    }


# -------------------------------------------------------------------
# Experiment 4: Real Live DXGI Vector Trajectory & Angular Distance
# -------------------------------------------------------------------
def test_live_dxgi_angular_velocity():
    cap = DXGIScreenCapture()
    try:
        f1 = cap.grab()
        if f1 is None:
            return {"status": "DXGI unavailable"}
        time.sleep(0.05)
        f2 = cap.grab()
        if f2 is None:
            f2 = f1

        # Fast pseudo-embedding: downsampled 16x16x3 = 768-dim normalized vector
        v1 = f1[::1080//16, ::1920//16, :][:16, :16, :].astype(np.float32).flatten()
        v2 = f2[::1080//16, ::1920//16, :][:16, :16, :].astype(np.float32).flatten()

        v1 /= np.linalg.norm(v1)
        v2 /= np.linalg.norm(v2)

        cos_sim = float(np.dot(v1, v2))
        cos_sim = max(-1.0, min(1.0, cos_sim))
        angular_dist_rad = np.arccos(cos_sim)
        angular_dist_deg = np.degrees(angular_dist_rad)

        return {
            "dim": len(v1),
            "cos_sim": round(cos_sim, 5),
            "angular_distance_deg": round(angular_dist_deg, 3),
            "status": "success",
        }
    finally:
        cap.stop()


def main():
    print("=" * 70)
    print("KERNEL + VECTOR EXPERIMENTS FOR SENSORY VISION")
    print("=" * 70)

    # Exp 1
    res1 = benchmark_vector_quantization()
    print("\n[Exp 1: Vector Quantization (768-dim, 1000 vectors)]")
    print(f"  FP32 Dot Product: {res1['t_fp32_ms']:.4f} ms (Memory: {res1['mem_fp32_kb']:.1f} KB)")
    print(f"  SQ8  Dot Product: {res1['t_sq8_ms']:.4f} ms (Memory: {res1['mem_sq8_kb']:.1f} KB, -75% RAM)")
    print(f"  Top-10 Recall Overlap: {res1['top10_overlap']}/10")

    # Exp 2
    res2 = benchmark_lancedb_kernel_metadata_filtering()
    print("\n[Exp 2: LanceDB Kernel Process-Scoped Vector Search (2000 vectors)]")
    print(f"  Unfiltered Search: {res2['t_unfiltered_ms']:.3f} ms")
    print(f"  Process Filtered (pid={res2['filtered_pids'][0]}): {res2['t_filtered_ms']:.3f} ms")

    # Exp 3
    res3 = benchmark_patch_token_caching()
    print("\n[Exp 3: ViT Patch Token Caching via Kernel DirtyRects]")
    print(f"  Full Patch Projection: {res3['t_full_ms']:.4f} ms")
    print(f"  Dirty-Only Patch Projection: {res3['t_sparse_ms']:.4f} ms")
    print(f"  Speedup: {res3['speedup']:.2f}x (Compute saved: {res3['computation_saved_pct']:.1f}%)")

    # Exp 4
    res4 = test_live_dxgi_angular_velocity()
    print("\n[Exp 4: Live DXGI Desktop Vector Trajectory]")
    print(f"  Vector Dim: {res4.get('dim')}")
    print(f"  Cosine Similarity: {res4.get('cos_sim')}")
    print(f"  Angular Distance: {res4.get('angular_distance_deg')} deg")
    print(f"  Status: {res4.get('status')}")


if __name__ == "__main__":
    main()
