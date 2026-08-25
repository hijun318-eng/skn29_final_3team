from typing import List

SYSTEM_PROMPT = """당신은 내부 업무 매뉴얼 근거 답변기다.
제공된 evidence 밖의 사실을 만들지 않는다.
절차, 조건, 예외, 금지사항을 evidence에 있는 범위에서만 설명한다.
각 사실 주장에는 evidence_id를 연결한다.
근거가 없으면 추측하지 않고 NO_EVIDENCE를 반환한다.
문서가 충돌하면 임의로 하나를 선택하지 않고 차이와 문서 버전·유효기간을 설명한다.
권한, 문서 상태, 유효기간을 재판정하지 않는다.
반드시 지정된 JSON schema 하나만 반환한다."""


def build_answer_prompt(query: str, evidence_blocks: List[dict]) -> List[dict]:
    """
    Builds the messages for the chat completion API.
    """
    evidence_text = "\n\n".join(
        "\n".join(
            (
                f"ID: {block['evidence_id']}",
                f"문서명: {block.get('title', '')}",
                f"지침번호: {block.get('manual_id', '')}",
                f"영역: {block.get('section_title', '')}",
                f"근거: {block.get('citation', '')}",
                "본문내용:",
                str(block.get("content") or block.get("text") or block.get("snippet") or ""),
            )
        )
        for block in evidence_blocks
    )

    user_prompt = f"질문: {query}\n\n제공된 근거(evidence):\n{evidence_text}\n\nEND_EVIDENCE\n\n위 근거를 바탕으로 JSON 형식으로만 답변하시오."

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
