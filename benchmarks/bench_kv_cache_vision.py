"""Experimental verification of KV-Cache Vision Hypotheses.

Tests:
1. KV Cache Quantization Error & Compression (FP16 vs Q8_0 vs Q4_0) on Visual Tokens
2. Attention-Sparsity & Heavy-Hitter (H2O/SnapKV) Visual Token Pruning
3. Prefix-Sharing & KV-Shift Latency Simulator
4. Spatial KV Cache Patch Update (Updating only changed patch tokens)
"""

from __future__ import annotations

import time
import numpy as np

# -------------------------------------------------------------------
# Experiment 1: Visual Token KV Cache Quantization (FP16 vs Q8 vs Q4)
# -------------------------------------------------------------------
def benchmark_kv_cache_quantization():
    # Architecture params of 9B-class model (e.g. 32 layers, GQA with 8 KV heads, head_dim=128)
    # A single frame with 256 visual tokens produces: 256 tokens * 32 layers * 8 heads * 128 dim
    n_tokens = 256
    n_layers = 32
    n_kv_heads = 8
    head_dim = 128
    total_elements = n_tokens * n_layers * n_kv_heads * head_dim

    # Generate synthetic FP16 visual Key tensors (Gaussian with typical scale)
    keys_fp16 = np.random.randn(total_elements).astype(np.float16)
    values_fp16 = np.random.randn(total_elements).astype(np.float16)

    size_fp16_mb = (keys_fp16.nbytes + values_fp16.nbytes) / (1024 * 1024)

    # Q8_0 quantization (block size 32): 8-bit int + float16 scale per block
    block_size = 32
    n_blocks = total_elements // block_size
    reshaped_k = keys_fp16.reshape(n_blocks, block_size).astype(np.float32)
    scales_q8 = np.max(np.abs(reshaped_k), axis=1, keepdims=True) / 127.0
    scales_q8[scales_q8 == 0] = 1.0
    quant_q8 = np.clip(np.round(reshaped_k / scales_q8), -127, 127).astype(np.int8)
    dequant_q8 = (quant_q8.astype(np.float32) * scales_q8).astype(np.float16).flatten()
    mse_q8 = float(np.mean((keys_fp16.astype(np.float32) - dequant_q8.astype(np.float32)) ** 2))
    size_q8_mb = (quant_q8.nbytes * 2 + scales_q8.nbytes * 2) / (1024 * 1024)

    # Q4_0 quantization (block size 32): 4-bit nibbles + float16 scale per block
    scales_q4 = np.max(np.abs(reshaped_k), axis=1, keepdims=True) / 7.0
    scales_q4[scales_q4 == 0] = 1.0
    quant_q4 = np.clip(np.round(reshaped_k / scales_q4), -7, 7).astype(np.int8)
    dequant_q4 = (quant_q4.astype(np.float32) * scales_q4).astype(np.float16).flatten()
    mse_q4 = float(np.mean((keys_fp16.astype(np.float32) - dequant_q4.astype(np.float32)) ** 2))
    size_q4_mb = (quant_q4.nbytes + scales_q4.nbytes * 2) / (1024 * 1024)

    return {
        "n_tokens": n_tokens,
        "size_fp16_mb": round(size_fp16_mb, 2),
        "size_q8_mb": round(size_q8_mb, 2),
        "size_q4_mb": round(size_q4_mb, 2),
        "mse_q8": round(mse_q8, 6),
        "mse_q4": round(mse_q4, 6),
    }


# -------------------------------------------------------------------
# Experiment 2: Attention Sparsity & Heavy-Hitter (H2O/SnapKV) Pruning
# -------------------------------------------------------------------
def benchmark_attention_kv_pruning():
    # 256 visual tokens + 64 prompt tokens
    n_vis = 256
    n_prompt = 64
    n_total = n_vis + n_prompt

    # Query vector from recent turn
    q = np.random.randn(1, 128).astype(np.float32)
    # Keys for visual and prompt tokens
    k = np.random.randn(n_total, 128).astype(np.float32)

    # Softmax attention distribution
    logits = np.dot(q, k.T) / np.sqrt(128)
    attn = np.exp(logits - np.max(logits))
    attn /= np.sum(attn)
    attn_scores = attn.flatten()

    # Sort tokens by attention weight
    vis_scores = attn_scores[:n_vis]
    sorted_idx = np.argsort(-vis_scores)

    # Cumulative attention mass retained
    sorted_mass = np.cumsum(vis_scores[sorted_idx])
    # How many tokens needed for 90% and 95% of attention mass?
    tokens_for_90 = int(np.searchsorted(sorted_mass, 0.90 * np.sum(vis_scores)) + 1)
    tokens_for_95 = int(np.searchsorted(sorted_mass, 0.95 * np.sum(vis_scores)) + 1)

    pruning_ratio_90 = (1.0 - tokens_for_90 / n_vis) * 100
    pruning_ratio_95 = (1.0 - tokens_for_95 / n_vis) * 100

    return {
        "n_vis_tokens": n_vis,
        "tokens_for_90_pct_mass": tokens_for_90,
        "tokens_for_95_pct_mass": tokens_for_95,
        "pruning_ratio_90": round(pruning_ratio_90, 1),
        "pruning_ratio_95": round(pruning_ratio_95, 1),
    }


# -------------------------------------------------------------------
# Experiment 3: Spatial KV Cache Paging (Selective Patch KV Invalidation)
# -------------------------------------------------------------------
def benchmark_spatial_kv_paging():
    # Grid of 16x16 visual tokens = 256 tokens in KV cache
    grid_size = 16
    total_tokens = grid_size * grid_size
    head_dim = 128
    n_layers = 32

    # Initial KV cache state
    kv_cache_k = np.random.randn(n_layers, total_tokens, head_dim).astype(np.float16)

    # Localized screen change: e.g. 4x4 patch region changed (16 tokens)
    changed_y0, changed_y1 = 6, 10
    changed_x0, changed_x1 = 6, 10
    changed_indices = []
    for y in range(changed_y0, changed_y1):
        for x in range(changed_x0, changed_x1):
            changed_indices.append(y * grid_size + x)

    # Full re-computation of 256 tokens
    t0 = time.perf_counter()
    for _ in range(500):
        new_k_full = np.random.randn(n_layers, total_tokens, head_dim).astype(np.float16)
        kv_cache_k[:] = new_k_full
    t_full = (time.perf_counter() - t0) / 500 * 1000

    # Paged in-place slice update of only 16 changed tokens
    t1 = time.perf_counter()
    for _ in range(500):
        new_k_slice = np.random.randn(n_layers, len(changed_indices), head_dim).astype(np.float16)
        kv_cache_k[:, changed_indices, :] = new_k_slice
    t_paged = (time.perf_counter() - t1) / 500 * 1000

    return {
        "total_tokens": total_tokens,
        "changed_tokens": len(changed_indices),
        "t_full_ms": round(t_full, 4),
        "t_paged_ms": round(t_paged, 4),
        "speedup": round(t_full / max(0.0001, t_paged), 2),
    }


def main():
    print("=" * 70)
    print("KV-CACHE VISION & SCENE INJECTION EXPERIMENTS")
    print("=" * 70)

    # Exp 1
    r1 = benchmark_kv_cache_quantization()
    print("\n[Exp 1: Visual Token KV-Cache Quantization (256 tokens, 32 layers)]")
    print(f"  FP16 Size: {r1['size_fp16_mb']} MB (Baseline)")
    print(f"  Q8_0 Size: {r1['size_q8_mb']} MB (MSE: {r1['mse_q8']:.6f})")
    print(f"  Q4_0 Size: {r1['size_q4_mb']} MB (MSE: {r1['mse_q4']:.6f}, -75% VRAM footprint)")

    # Exp 2
    r2 = benchmark_attention_kv_pruning()
    print("\n[Exp 2: Attention Sparsity & Heavy-Hitter (H2O/SnapKV) Pruning]")
    print(f"  Total Visual Tokens: {r2['n_vis_tokens']}")
    print(f"  Tokens for 90% Attention Mass: {r2['tokens_for_90_pct_mass']} ({r2['pruning_ratio_90']}% pruned)")
    print(f"  Tokens for 95% Attention Mass: {r2['tokens_for_95_pct_mass']} ({r2['pruning_ratio_95']}% pruned)")

    # Exp 3
    r3 = benchmark_spatial_kv_paging()
    print("\n[Exp 3: Spatial KV Cache Paging (Selective Patch Invalidation)]")
    print(f"  Total Screen Tokens: {r3['total_tokens']}, Updated Patches: {r3['changed_tokens']}")
    print(f"  Full KV Re-evaluation: {r3['t_full_ms']} ms")
    print(f"  Selective Paged In-Place Update: {r3['t_paged_ms']} ms")
    print(f"  Speedup: {r3['speedup']}x")


if __name__ == "__main__":
    main()
