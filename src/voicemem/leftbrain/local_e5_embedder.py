from __future__ import annotations
from functools import lru_cache
import numpy as np
import os as _os

def _e5_name() -> str:
    from voicemem.utils.common.paths import hf_model
    return hf_model("embedding", "intfloat/multilingual-e5-small", "VOICEMEM_E5_MODEL")

_E5_NAME = _e5_name()

@lru_cache(maxsize=1)
def shared_e5():
    """Cache embedding model (local SentenceTransformer or in-tree EG2 ONNX)."""
    if _os.environ.get("VOICEMEM_VERBOSE", "0") == "0":
        try:
            from transformers.utils import logging as _hf_logging
            _hf_logging.disable_progress_bar()
        except Exception:
            pass
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(_E5_NAME)
    except Exception:
        from jawl_voicecompanion.eg2_sensory import DEFAULT_EG2_ONNX_ROOT, EmbeddingGemmaSensoryCortex
        cortex = EmbeddingGemmaSensoryCortex(DEFAULT_EG2_ONNX_ROOT)
        class _CortexAdapter:
            def __init__(self, cortex):
                self._cortex = cortex
            def get_sentence_embedding_dimension(self):
                return 768
            def get_embedding_dimension(self):
                return 768
            def encode(self, texts, normalize_embeddings=True):
                vecs = [self._cortex.embed_text(t) for t in texts]
                arr = np.asarray(vecs, dtype=np.float32)
                if normalize_embeddings and len(arr) > 0:
                    norms = np.linalg.norm(arr, axis=1, keepdims=True)
                    norms[norms == 0] = 1.0
                    arr = arr / norms
                return arr
        return _CortexAdapter(cortex)

class LocalE5Embedder:
    """Zero-network embedding adapter (SentenceTransformer or in-tree EG2 ONNX)."""

    @property
    def model_name(self):
        return f"{_E5_NAME} (local-or-eg2)"

    @property
    def dimensions(self):
        m = shared_e5()
        fn = getattr(m, "get_embedding_dimension", None) or getattr(m, "get_sentence_embedding_dimension", None)
        return fn() if callable(fn) else 768

    def embed_texts(self, texts):
        if not texts:
            return []
        return np.asarray(shared_e5().encode([f"passage: {t}" for t in texts],
                                             normalize_embeddings=True)).tolist()

    def embed_query_text(self, text):
        return np.asarray(shared_e5().encode([f"query: {text}"], normalize_embeddings=True)[0]).tolist()
