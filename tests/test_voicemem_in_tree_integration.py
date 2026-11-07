import sys
import unittest
from pathlib import Path
import tempfile
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys_src = str(ROOT / "src")
if sys_src not in sys.path:
    sys.path.insert(0, sys_src)


class TestVoiceMemInTreeIntegration(unittest.TestCase):
    def test_in_tree_import(self):
        """VoiceMem can be imported directly from in-tree sources."""
        import voicemem
        self.assertTrue(hasattr(voicemem, "VoiceMem"))
        from jawl_voicecompanion import voicemem as j_voicemem
        self.assertTrue(hasattr(j_voicemem, "VoiceMem"))

    def test_local_sqlite_vector_store(self):
        """LocalSqliteMemory performs vector search and CRUD natively without external servers."""
        from voicemem.leftbrain.mem0_backend_store import LocalSqliteMemory

        class MockEmbedder:
            def embed(self, text, op_type="add"):
                if "tea" in text:
                    return [1.0, 0.0, 0.0]
                return [0.0, 1.0, 0.0]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = str(Path(tmpdir) / "test_mem.db")
            store = LocalSqliteMemory(db_file, embedder=MockEmbedder())

            res = store.add(messages=[{"role": "user", "content": "User likes green tea"}], user_id="user_1")
            self.assertEqual(len(res["results"]), 1)
            item_a = res["results"][0]
            self.assertEqual(item_a["memory"], "User likes green tea")

            res_b = store.add(messages=[{"role": "user", "content": "User is a Python developer"}], user_id="user_1")
            item_b = res_b["results"][0]

            # Query with mock embedder returning tea vector
            search_res = store.search(query="tea", filters={"user_id": "user_1"}, top_k=2)
            results = search_res.get("results", [])
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["id"], item_a["id"])
            self.assertGreater(results[0]["score"], results[1]["score"])

            # Test get_all
            all_res = store.get_all(filters={"user_id": "user_1"})
            self.assertEqual(len(all_res.get("results", [])), 2)

            # Test update
            store.update(memory_id=item_a["id"], data="User prefers matcha green tea")
            updated = store.get(memory_id=item_a["id"])
            self.assertEqual(updated["memory"], "User prefers matcha green tea")

            # Test delete
            store.delete(memory_id=item_b["id"])
            remaining = store.get_all(filters={"user_id": "user_1"}).get("results", [])
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0]["id"], item_a["id"])

    def test_local_embedder_dimension(self):
        """LocalE5Embedder returns normalized 768-dimensional embeddings."""
        from voicemem.leftbrain.local_e5_embedder import LocalE5Embedder
        embedder = LocalE5Embedder()
        self.assertEqual(embedder.dimensions, 768)
        vec = embedder.embed_query_text("Тестовый запрос")
        self.assertEqual(len(vec), 768)
        norm = float(np.linalg.norm(vec))
        self.assertAlmostEqual(norm, 1.0, places=3)

    def test_adr053_speculative_boundary(self):
        """VoiceMem acts strictly as speculative context generator and does not write canonical memory."""
        from voicemem import VoiceMem
        with tempfile.TemporaryDirectory() as tmpdir:
            vm = VoiceMem(mode="normal", memory_root=tmpdir)
            self.assertTrue(hasattr(vm, "search"))
            self.assertFalse(hasattr(vm, "write_canonical_jawl_memory"))


if __name__ == "__main__":
    unittest.main()
