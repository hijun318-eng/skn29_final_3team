from typing import List

SYSTEM_PROMPT = """당신은 내부 업무 매뉴얼 근거 답변기다.
제공된 evidence 밖의 사실을 만들지 않는다.
절차, 조건, 예외, 금지사항을 evidence에 있는 범위에서만 설명한다.
각 사실 주장에는 evidence_id를 연결한다.
요청 의도에 맞는 answer_type과 구조를 유지한다.
근거가 없으면 추측하지 않고 NO_EVIDENCE를 반환한다.
문서가 충돌하면 임의로 하나를 선택하지 않고 차이와 문서 버전·유효기간을 설명한다.
권한, 문서 상태, 유효기간을 재판정하지 않는다.
반드시 지정된 JSON schema 하나만 반환한다."""


def build_answer_prompt(
    query: str,
    evidence_blocks: List[dict],
    intent: str = "REGULATION_CHECK",
) -> List[dict]:
    """
    Builds the messages for the chat completion API.
    """
    evidence_text = "\n\n".join(
        "\n".join(
            (
                f"ID: {block['evidence_id']}",
                f"문서ID: {block.get('document_id') or block.get('manual_id', '')}",
                f"문서명: {block.get('title', '')}",
                f"지침번호: {block.get('manual_id', '')}",
                f"버전: {block.get('version', '')}",
                f"영역: {block.get('section_title', '')}",
                f"조항번호: {block.get('article_number', '')}",
                f"페이지: {block.get('page_start', '')}",
                f"청크ID: {block.get('chunk_id', '')}",
                f"청크순서: {block.get('chunk_index', '')}",
                f"검색점수: {block.get('score', block.get('retrieval_score', ''))}",
                f"벡터점수: {block.get('vector_score', '')}",
                f"어휘점수: {block.get('lexical_score', '')}",
                f"문서상태: {block.get('document_status', '')}",
                f"승인상태: {block.get('approval_status', '')}",
                f"유효성상태: {block.get('validity_status', '')}",
                f"유효시작일: {block.get('effective_from', '')}",
                f"유효종료일: {block.get('effective_to') or block.get('expires_at', '')}",
                f"근거: {block.get('citation', '')}",
                "본문내용:",
                str(block.get("content") or block.get("text") or block.get("snippet") or ""),
            )
        )
        for block in evidence_blocks
    )

    user_prompt = (
        f"질문: {query}\n"
        f"요청 의도: {intent}\n\n"
        f"제공된 근거(evidence):\n{evidence_text}\n\nEND_EVIDENCE\n\n"
        "위 근거를 바탕으로 JSON 형식으로만 답변하시오."
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
