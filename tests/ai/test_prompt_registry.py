import unittest

from src.ai.prompt_registry import get_prompt, list_prompt_metadata


class PromptRegistryTests(unittest.TestCase):
    def test_registry_tracks_id_version_environment_and_hash(self):
        first = list_prompt_metadata()
        second = list_prompt_metadata()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertEqual(
            {
                "node1.normalize": "PROMPT-v1.0.0",
                "node2.repair": "PROMPT-v1.0.1",
                "node2.sql": "PROMPT-v1.0.1",
                "node3.explain": "PROMPT-v1.0.0",
            },
            {item["prompt_id"]: item["version"] for item in first},
        )
        for metadata in first:
            self.assertEqual(metadata["environment"], "development")
            self.assertEqual(metadata["model_version"], "DRAFT-BASE-v0.1")
            self.assertIsNone(metadata["fixture_version"])
            self.assertEqual(len(metadata["hash"]), 64)

    def test_node1_and_node3_have_no_sql_adapter(self):
        for prompt_id in ("node1.normalize", "node3.explain"):
            prompt = get_prompt(prompt_id)
            self.assertEqual(prompt.model_profile, "base")
            self.assertIsNone(prompt.adapter)

    def test_node2_prompts_define_resource_limit_and_single_repair(self):
        sql_prompt = get_prompt("node2.sql").text
        repair_prompt = get_prompt("node2.repair").text

        self.assertIn("1 이상 1000 이하 정수의 LIMIT", sql_prompt)
        self.assertIn("RESOURCE_POLICY_MISSING", repair_prompt)
        self.assertIn("LIMIT 1000을 추가", repair_prompt)
        self.assertIn("한 번 수정", repair_prompt)


if __name__ == "__main__":
    unittest.main()
