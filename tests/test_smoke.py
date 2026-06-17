import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class SmokeTests(unittest.TestCase):
    def test_config_paths_are_repo_relative(self):
        from medical_lab_ai_core.core import config

        self.assertEqual(config.BASE_DIR, ROOT)
        self.assertTrue(config.QDRANT_HOST)
        self.assertTrue(config.COLLECTION_NAME)

    def test_basic_lab_core_normalization(self):
        from medical_lab_ai_core.core import config

        self.assertEqual(config.STATUS_NORMALIZATION["high"], "high")
        self.assertIn("WBC", config.TEST_LABELS)

    def test_neo4j_password_default_is_placeholder(self):
        source = ROOT / "src" / "medical_lab_ai_core" / "retrieval" / "neo4j_retriever.py"
        text = source.read_text(encoding="utf-8")

        old_password_literal = "25" + "251325"
        self.assertNotIn(old_password_literal, text)
        self.assertIn('os.getenv("NEO4J_PASSWORD", "password")', text)


if __name__ == "__main__":
    unittest.main()
