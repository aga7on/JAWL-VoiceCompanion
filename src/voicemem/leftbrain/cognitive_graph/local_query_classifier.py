from __future__ import annotations
from typing import Callable, Sequence
import numpy as np

from voicemem.leftbrain.cognitive_graph.query_slot_classifier import QueryClassification

def _model_name() -> str:
    from voicemem.utils.common.paths import hf_model
    return hf_model("embedding", "intfloat/multilingual-e5-small", "VOICEMEM_E5_MODEL")

_MODEL_NAME = _model_name()

_SLOT_DESCRIPTIONS = {
    "work": "career, job, company, projects, colleagues, workplace, работа, карьера, проект, начальник, офис, задачи, дедлайн, код, программирование",
    "finance": "money, salary, income, expenses, investments, savings, деньги, зарплата, покупка, счет, карта, инвестиции, бюджет, расходы, рубли",
    "relationships": "friends, family, romantic, social connections, друзья, семья, отношения, знакомство, общение",
    "health": "physical health, exercise, diet, sleep, medical, здоровье, врач, лекарства, спорт, усталость, боль, сон, температура, самочувствие",
    "goals": "future plans, dreams, aspirations, self-improvement, цели, планы, мечты, будущее, развитие, изучение, задача на год",
    "daily_life": "daily routines, hobbies, leisure, lifestyle, погода, еда, ужин, чай, кофе, фильм, музыка, прогулка, уборка, быт, хобби",
    "knowledge": "learning, concepts, skills, facts, technology, знания, навыки, обучение, факты, наука, технологии",
}

class LocalQueryClassifier:
    """query -> QueryClassification(slots, entities) local classifier."""

    def __init__(
        self,
        model_name: str = _MODEL_NAME,
        model=None,
        ner: Callable[[str], Sequence[str]] | None = None,
        top_k: int = 2,
    ) -> None:
        self._model_name = model_name
        self._model = model
        self._ner = ner
        self._top_k = top_k
        self._slot_names = list(_SLOT_DESCRIPTIONS)
        self._slot_embs = None

    def _m(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
            except Exception:
                from jawl_voicecompanion.eg2_sensory import DEFAULT_EG2_ONNX_ROOT, EmbeddingGemmaSensoryCortex
                cortex = EmbeddingGemmaSensoryCortex(DEFAULT_EG2_ONNX_ROOT)
                class _CortexAdapter:
                    def __init__(self, cortex):
                        self._cortex = cortex
                    def encode(self, texts, normalize_embeddings=True):
                        vecs = [self._cortex.embed_text(t) for t in texts]
                        arr = np.asarray(vecs, dtype=np.float32)
                        if normalize_embeddings and len(arr) > 0:
                            norms = np.linalg.norm(arr, axis=1, keepdims=True)
                            norms[norms == 0] = 1.0
                            arr = arr / norms
                        return arr
                self._model = _CortexAdapter(cortex)
        return self._model

    def _slots_matrix(self):
        if self._slot_embs is None:
            texts = [f"passage: {k}: {v}" for k, v in _SLOT_DESCRIPTIONS.items()]
            self._slot_embs = np.asarray(self._m().encode(texts, normalize_embeddings=True))
        return self._slot_embs

    def classify(self, query: str, extra_slots=None) -> QueryClassification:
        q = np.asarray(self._m().encode([f"query: {query}"], normalize_embeddings=True)[0])
        order = np.argsort(-(self._slots_matrix() @ q))[: self._top_k]
        slots = [self._slot_names[i] for i in order]
        entities = list(self._ner(query)) if self._ner else []
        return QueryClassification(slots=slots, entities=entities)
