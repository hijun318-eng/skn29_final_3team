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
                "node2.repair": "PROMPT-v1.0.2",
                "node2.sql": "PROMPT-v1.0.6",
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

        self.assertIn("normalized_question에서만", sql_prompt)
        self.assertIn("question_id는 추적 식별자", sql_prompt)
        self.assertIn("한 줄로 작성", sql_prompt)
        self.assertIn("불필요한 공백이나 개행", sql_prompt)
        self.assertIn("1 이상 1000 이하 정수의 LIMIT", sql_prompt)
        self.assertIn("FROM과 JOIN에 실제 사용한", sql_prompt)
        self.assertIn("양방향 정확히 일치", sql_prompt)
        self.assertIn("사용하지 않은 asset", sql_prompt)
        self.assertIn("사용한 table을 누락하지 않는다", sql_prompt)
        self.assertIn("없는 컬럼이나 JOIN 단축 경로를 만들지 않는다", sql_prompt)
        self.assertIn("SQL table 이름이 아니라 승인 JOIN 식별자", sql_prompt)
        self.assertIn("FROM pms.public.pms_stays s JOIN pms.public.pms_reservations r", sql_prompt)
        self.assertIn("승인 metric의 aggregation", sql_prompt)
        self.assertIn("문자열이나 BETWEEN이 아니라 TIMESTAMP", sql_prompt)
        self.assertIn("CURRENT_DATE·CURRENT_TIMESTAMP·now 함수는 쓰지 않고", sql_prompt)
        self.assertIn("직전 완료 월과 그 이전 월만 조회", sql_prompt)
        self.assertIn("date_add('month', -2, from_iso8601_timestamp", sql_prompt)
        self.assertIn("GROUP BY 1 ORDER BY 1", sql_prompt)
        self.assertIn("실제 사용한 :name placeholder만 같은 이름", sql_prompt)
        self.assertIn("placeholder가 없으면 빈 배열", sql_prompt)
        self.assertIn("request metadata는 parameters에 포함하지 않는다", sql_prompt)
        self.assertIn("RESOURCE_POLICY_MISSING", repair_prompt)
        self.assertIn("LIMIT 1000을 추가", repair_prompt)
        self.assertIn("SQL_REFERENCE_MISMATCH", repair_prompt)
        self.assertIn("corrected_sql의 FROM·JOIN table 집합", repair_prompt)
        self.assertIn("references의 trino_fqn 집합", repair_prompt)
        self.assertIn("승인 asset 안에서 양방향 정확히 일치", repair_prompt)
        self.assertIn("한 번 수정", repair_prompt)


if __name__ == "__main__":
    unittest.main()
