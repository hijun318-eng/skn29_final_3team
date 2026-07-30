import unittest

from src.ai.prompt_registry import get_prompt, list_prompt_metadata


class PromptRegistryTests(unittest.TestCase):
    def test_registry_tracks_id_version_environment_and_hash(self):
        first = list_prompt_metadata()
        second = list_prompt_metadata()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        for metadata in first:
            self.assertEqual(metadata["version"], "DRAFT-PROMPT-v0.1")
            self.assertEqual(metadata["environment"], "development")
            self.assertEqual(metadata["model_version"], "DRAFT-BASE-v0.1")
            self.assertIsNone(metadata["fixture_version"])
            self.assertEqual(len(metadata["hash"]), 64)

    def test_node1_and_node3_have_no_sql_adapter(self):
        for prompt_id in ("node1.normalize", "node3.explain"):
            prompt = get_prompt(prompt_id)
            self.assertEqual(prompt.model_profile, "base")
            self.assertIsNone(prompt.adapter)


if __name__ == "__main__":
    unittest.main()
