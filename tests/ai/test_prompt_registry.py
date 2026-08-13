import unittest

from src.ai.prompt_registry import get_prompt, list_prompt_metadata


class PromptRegistryTests(unittest.TestCase):
    def test_registry_tracks_id_version_environment_and_hash(self):
        first = list_prompt_metadata()
        second = list_prompt_metadata()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        self.assertEqual(
            {
                "node1.normalize": "PROMPT-v1.2.0",
                "node2.repair": "PROMPT-v1.2.11",
                "node2.sql": "PROMPT-v1.2.13",
                "node3.explain": "PROMPT-v1.2.1",
                "report.assistant": "PROMPT-v1.0.0",
            },
            {item["prompt_id"]: item["version"] for item in first},
        )
        for metadata in first:
            self.assertEqual(metadata["environment"], "development")
            self.assertEqual(metadata["model_version"], "DRAFT-BASE-v0.1")
            self.assertIsNone(metadata["fixture_version"])
            self.assertEqual(len(metadata["hash"]), 64)

    def test_node1_and_node3_have_no_sql_adapter(self):
        for prompt_id in ("node1.normalize", "node3.explain", "report.assistant"):
            prompt = get_prompt(prompt_id)
            self.assertEqual(prompt.model_profile, "base")
            self.assertIsNone(prompt.adapter)

    def test_each_node_has_a_distinct_role_and_prompt_hash(self):
        prompts = {
            prompt_id: get_prompt(prompt_id)
            for prompt_id in (
                "node1.normalize",
                "node2.sql",
                "node2.repair",
                "node3.explain",
            )
        }
        self.assertEqual(4, len({item.metadata()["hash"] for item in prompts.values()}))
        self.assertIn("question interpreter", prompts["node1.normalize"].text)
        self.assertIn("never return SQL", prompts["node1.normalize"].text)
        self.assertIn("read-only Trino SELECT", prompts["node2.sql"].text)
        self.assertIn("한 번 수정", prompts["node2.repair"].text)
        self.assertIn("사용자용 근거 설명자", prompts["node3.explain"].text)
        self.assertIn("자연스러운 한국어 2~4문장", prompts["node3.explain"].text)
        self.assertIn("SQL을 생성·수정", prompts["node3.explain"].text)
        assistant = get_prompt("report.assistant")
        self.assertNotIn(assistant.metadata()["hash"], {item.metadata()["hash"] for item in prompts.values()})
        self.assertIn("APPROVED Analysis Artifact", assistant.text)
        self.assertIn("Do not generate SQL", assistant.text)

    def test_node2_prompts_define_resource_limit_and_single_repair(self):
        sql_prompt = get_prompt("node2.sql").text
        self.assertNotIn("SYNTHETIC_HOTEL_001", sql_prompt)
        self.assertIn("Context에 없는 기본값을 만들지 않는다", sql_prompt)
        repair_prompt = get_prompt("node2.repair").text

        self.assertIn("normalized_question에서만", sql_prompt)
        self.assertIn("question_id는 추적 식별자", sql_prompt)
        self.assertIn("한 줄로 작성", sql_prompt)
        self.assertIn("불필요한 공백이나 개행", sql_prompt)
        self.assertIn("1 이상 1000 이하 정수의 LIMIT", sql_prompt)
        self.assertIn("sql, used_assets, used_metrics 세 필드만", sql_prompt)
        self.assertIn("실제 사용한 승인 trino_fqn", sql_prompt)
        self.assertIn("설명·Markdown·references·parameters 없이", sql_prompt)
        self.assertIn("실제 사용하는 승인 Context asset", sql_prompt)
        self.assertIn("없는 컬럼이나 JOIN 단축 경로를 만들지 않는다", sql_prompt)
        self.assertIn("asset·metric required_filters", sql_prompt)
        self.assertIn("required_source_predicates만 적용", sql_prompt)
        self.assertIn("year_month도 월 첫날 DATE", sql_prompt)
        self.assertIn("SQL table 이름이 아니라 승인 JOIN 식별자", sql_prompt)
        self.assertIn("FROM pms.public.pms_stays s JOIN pms.public.pms_reservations r", sql_prompt)
        self.assertIn("Context metric의 field·aggregation·time_field", sql_prompt)
        self.assertIn("required_filters", sql_prompt)
        self.assertIn("operator eq를 =로 변환", sql_prompt)
        self.assertIn("자유 형식 predicate로 해석하지 않는다", sql_prompt)
        self.assertIn("Context asset의 column_types를 우선한다", sql_prompt)
        self.assertIn("POS ordered_at은 DATETIME(3)", sql_prompt)
        self.assertIn("두 CTE의 month 결합 키는 같은 varchar 형식", sql_prompt)
        self.assertIn("CURRENT_DATE·CURRENT_TIMESTAMP·now 함수는 쓰지 않고", sql_prompt)
        self.assertIn("직전 완료 월과 그 이전 월만 조회", sql_prompt)
        self.assertIn("date_add('month', -2, from_iso8601_timestamp", sql_prompt)
        self.assertIn("GROUP BY 1 ORDER BY 1", sql_prompt)
        self.assertIn("PMS·CRM 객실 매출 CTE와 POS·CRM 식음 매출 CTE", sql_prompt)
        self.assertIn("PMS 행과 POS 주문을 직접 JOIN하지 않는다", sql_prompt)
        self.assertIn("AS total_guest_revenue_krw", sql_prompt)
        self.assertIn("total_revenue 같은 임의 alias", sql_prompt)
        self.assertIn("값이 같아도 다른 번호를 재사용하지 않는다", sql_prompt)
        self.assertIn("o.order_status IN ('PAID','PARTIAL_REFUND')", sql_prompt)
        self.assertIn("required_filters를 asset_fqn·field별로 하나씩 대조", sql_prompt)
        self.assertIn("일부 조건을 적용한 것으로 검사를 끝내지 않는다", sql_prompt)
        self.assertIn("placeholder는 만들지 않는다", sql_prompt)
        self.assertIn("없으면 LIMIT 1000", sql_prompt)
        self.assertIn('{"corrected_sql":"한 줄 SQL"}', repair_prompt)
        self.assertIn("RESOURCE_POLICY_MISSING", repair_prompt)
        self.assertIn("LIMIT 1000을 추가", repair_prompt)
        self.assertIn("SQL_REFERENCE_MISMATCH", repair_prompt)
        self.assertIn("corrected_sql의 FROM·JOIN table 집합", repair_prompt)
        self.assertIn("승인 Context asset 안으로 제한", repair_prompt)
        self.assertIn(
            "각 required_filter_N의 원래 asset_fqn·field·parameter_name 대응",
            repair_prompt,
        )
        self.assertIn("o.payment_status IN ('PAID','PARTIAL_REFUND')", repair_prompt)
        self.assertIn("METRIC_FILTER_MISSING", repair_prompt)
        self.assertIn("모든 required_filters를 AND 조건", repair_prompt)
        self.assertIn("전체 필터 묶음 위반", repair_prompt)
        self.assertIn("일부 조건을 고친 뒤 반환하지 말고", repair_prompt)
        self.assertIn("PARAMETERS_INVALID", repair_prompt)
        self.assertIn("METRIC_REFERENCE_MISMATCH", repair_prompt)
        self.assertIn("violation_detail은 현재 Context에서 계산된 권위 있는 수정 제약", repair_prompt)
        self.assertIn("두 CTE를 모두 고친다", repair_prompt)
        self.assertIn("한 번 수정", repair_prompt)


if __name__ == "__main__":
    unittest.main()
