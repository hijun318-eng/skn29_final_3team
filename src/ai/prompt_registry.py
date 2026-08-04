"""Versioned prompts with stable hashes for request tracing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256


@dataclass(frozen=True)
class PromptRecord:
    prompt_id: str
    version: str
    node: str
    environment: str
    model_profile: str
    adapter: str | None
    model_version: str
    text: str

    def metadata(self) -> dict[str, str | None]:
        result = asdict(self)
        result.pop("text")
        result["fixture_version"] = None
        result["hash"] = sha256(self.text.encode("utf-8")).hexdigest()
        return result


_PROMPTS = {
    "node1.normalize": PromptRecord(
        "node1.normalize",
        "PROMPT-v1.0.0",
        "node1",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "질문에서 intent, metric, dimension, 절대 기간 후보와 최소 재질문만 추출한다. "
        "자산·권한·Gate·SQL을 결정하지 않는다.",
    ),
    "node2.sql": PromptRecord(
        "node2.sql",
        "PROMPT-v1.0.6",
        "node2",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "승인 Context Package 안의 자산·컬럼·JOIN만 사용해 세미콜론 없는 단일 read-only Trino SELECT 후보를 만든다. "
        "SQL의 분석 의미는 normalized_question에서만 가져오고 question_id는 추적 식별자로만 취급한다. "
        "SQL 문자열은 한 줄로 작성하고 불필요한 공백이나 개행을 넣지 않는다. "
        "SQL 마지막에는 1 이상 1000 이하 정수의 LIMIT을 반드시 명시한다. "
        "references의 trino_fqn 집합은 SQL FROM과 JOIN에 실제 사용한 승인 Context asset의 trino_fqn 집합과 양방향 정확히 일치시키며, 사용하지 않은 asset을 넣거나 사용한 table을 누락하지 않는다. "
        "SQL의 모든 컬럼은 해당 Context asset의 columns에 있는 이름만 사용하고 없는 컬럼이나 JOIN 단축 경로를 만들지 않는다. "
        "pms_stay_to_crm_membership_grade_event_time_v1은 SQL table 이름이 아니라 승인 JOIN 식별자이므로 JOIN 뒤에 쓰지 않는다. "
        "이 JOIN은 FROM pms.public.pms_stays s JOIN pms.public.pms_reservations r ON s.property_id = r.property_id AND s.reservation_id = r.reservation_id JOIN pms.public.pms_guests g ON r.property_id = g.property_id AND r.guest_id = g.guest_id JOIN crm.dbo.crm_customer_map m ON g.property_id = m.property_id AND g.guest_id = m.pms_guest_id AND m.valid_from <= s.actual_checkout_at AND (m.valid_to IS NULL OR s.actual_checkout_at < m.valid_to) JOIN crm.dbo.crm_member_grade_history h ON m.property_id = h.property_id AND m.member_no = h.member_no AND h.valid_from <= s.actual_checkout_at AND (h.valid_to IS NULL OR s.actual_checkout_at < h.valid_to) 형태를 정확히 사용한다. "
        "지표 질문은 승인 metric의 aggregation을 적용하고 원시 식별자 행을 대신 반환하지 않는다. "
        "timestamp with time zone 기간은 문자열이나 BETWEEN이 아니라 TIMESTAMP 'YYYY-MM-DD 00:00:00 Asia/Seoul' 리터럴의 이상·미만 반개구간으로 비교한다. "
        "CURRENT_DATE·CURRENT_TIMESTAMP·now 함수는 쓰지 않고 Context execution_time의 절대 시각만 사용한다. "
        "전월 대비 월 지표는 원시 식별자나 valid_from·valid_to를 SELECT·GROUP BY하지 않고 date_format(date_trunc('month', s.actual_checkout_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m') 월과 SUM(s.room_revenue)만 SELECT한다. "
        "기간 조건은 s.actual_checkout_at >= date_add('month', -2, from_iso8601_timestamp('<execution_time.period_start 값>')) AND s.actual_checkout_at < from_iso8601_timestamp('<execution_time.period_start 값>') 형태로 직전 완료 월과 그 이전 월만 조회하고 GROUP BY 1 ORDER BY 1로 두 행을 반환한다. "
        "parameters에는 SQL에서 실제 사용한 :name placeholder만 같은 이름으로 포함하고, placeholder가 없으면 빈 배열을 반환한다. "
        "question_id와 normalized_question 등 request metadata는 parameters에 포함하지 않는다. "
        "실행과 정책 통과를 판정하지 않는다.",
    ),
    "node2.repair": PromptRecord(
        "node2.repair",
        "PROMPT-v1.0.2",
        "node2_repair",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "동일 Context에서 정규화 오류 코드에 해당하는 항목만 한 번 수정한다. "
        "RESOURCE_POLICY_MISSING이면 기존 의미·승인 reference·parameter를 유지하고 SQL 마지막에 LIMIT이 없으면 LIMIT 1000을 추가하며, 1000을 초과하면 LIMIT 1000으로 교체한다. "
        "SQL_REFERENCE_MISMATCH이면 질문 의미·승인 Context·parameter를 유지하고 corrected_sql의 FROM·JOIN table 집합과 references의 trino_fqn 집합을 승인 asset 안에서 양방향 정확히 일치시킨다. "
        "원문 오류를 해석하거나 반복 호출하지 않는다.",
    ),
    "node3.explain": PromptRecord(
        "node3.explain",
        "PROMPT-v1.0.0",
        "node3",
        "development",
        "base",
        None,
        "DRAFT-BASE-v0.1",
        "G3 pass shaped result의 조건·기간·단위·출처·제한만 설명한다. "
        "수치를 재계산하거나 원인을 단정하지 않는다.",
    ),
}


def get_prompt(prompt_id: str, environment: str = "development") -> PromptRecord:
    prompt = _PROMPTS[prompt_id]
    if prompt.environment != environment:
        raise KeyError(f"{prompt_id!r} is not registered for {environment!r}")
    return prompt


def list_prompt_metadata() -> list[dict[str, str | None]]:
    return [_PROMPTS[prompt_id].metadata() for prompt_id in sorted(_PROMPTS)]
