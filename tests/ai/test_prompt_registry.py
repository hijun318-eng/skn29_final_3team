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
                "node2.repair": "PROMPT-v1.0.4",
                "node2.sql": "PROMPT-v1.0.9-DRAFT",
                "node3.explain": "PROMPT-v1.0.0",
            },
            {item["prompt_id"]: item["version"] for item in first},
        )
        for metadata in first:
            self.assertEqual(metadata["environment"], "development")
            self.assertEqual(metadata["model_version"], "DRAFT-BASE-v0.1")
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
        self.assertIn('{"sql":"한 줄 SQL"}', sql_prompt)
        self.assertIn("설명·Markdown·references·parameters 없이", sql_prompt)
        self.assertIn("실제 사용하는 승인 Context asset", sql_prompt)
        self.assertIn("없는 컬럼이나 JOIN 단축 경로를 만들지 않는다", sql_prompt)
        self.assertIn("property_id = 'SYNTHETIC_HOTEL_001'", sql_prompt)
        self.assertIn("data_period_status가 있으면 'ACTUAL'", sql_prompt)
        self.assertIn("is_forecast가 있으면 false", sql_prompt)
        self.assertIn("year_month도 월 첫날 DATE", sql_prompt)
        self.assertIn("SQL table 이름이 아니라 승인 JOIN 식별자", sql_prompt)
        self.assertIn("FROM pms.public.pms_stays s JOIN pms.public.pms_reservations r", sql_prompt)
        self.assertIn("Context metric의 field·aggregation·time_field", sql_prompt)
        self.assertIn("required_filters", sql_prompt)
        self.assertIn("operator eq를 =로 변환", sql_prompt)
        self.assertIn("자유 형식 predicate로 해석하지 않는다", sql_prompt)
        self.assertIn("timestamp with time zone 기간만 TIMESTAMP", sql_prompt)
        self.assertIn("CURRENT_DATE·CURRENT_TIMESTAMP·now 함수는 쓰지 않고", sql_prompt)
        self.assertIn("직전 완료 월과 그 이전 월만 조회", sql_prompt)
        self.assertIn("date_add('month', -2, from_iso8601_timestamp", sql_prompt)
        self.assertIn("GROUP BY 1 ORDER BY 1", sql_prompt)
        self.assertIn("placeholder는 만들지 않는다", sql_prompt)
        self.assertIn("없으면 LIMIT 1000", sql_prompt)
        self.assertIn('{"corrected_sql":"한 줄 SQL"}', repair_prompt)
        self.assertIn("RESOURCE_POLICY_MISSING", repair_prompt)
        self.assertIn("LIMIT 1000을 추가", repair_prompt)
        self.assertIn("SQL_REFERENCE_MISMATCH", repair_prompt)
        self.assertIn("corrected_sql의 FROM·JOIN table 집합", repair_prompt)
        self.assertIn("승인 Context asset 안으로 제한", repair_prompt)
        self.assertIn("한 번 수정", repair_prompt)


if __name__ == "__main__":
    unittest.main()
