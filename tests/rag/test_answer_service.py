from __future__ import annotations

import json
from unittest.mock import patch

from src.rag.answer_contracts import AnswerRequest, AnswerResponse, GroundedModelOutput
from src.rag.answer_service import AnswerService
from src.rag.answer_prompt import serialize_evidence_blocks
from src.rag.answer_prompt import build_answer_prompt
from src.rag.local_answer_service import EvidenceBoundAnswerComposer


def test_answer_service_rejects_unapproved_plain_http_endpoint() -> None:
    try:
        AnswerService({}, "test-key", "http://external.example.test/v1/chat/completions")
    except ValueError as error:
        assert "endpoint is invalid" in str(error)
    else:
        raise AssertionError("external plain HTTP answer endpoint must be rejected")


def test_answer_service_allows_explicit_internal_plain_http_endpoint() -> None:
    service = AnswerService(
        {"allowed_http_hosts": ["rag-local-answer"]},
        "test-key",
        "http://rag-local-answer:8001/v1/chat/completions",
    )

    assert service.endpoint.startswith("http://rag-local-answer:8001/")


def test_answer_service_rejects_https_endpoint_outside_explicit_allowlist() -> None:
    try:
        AnswerService(
            {"allowed_https_hosts": ["api.openai.com"]},
            "test-key",
            "https://answer.example.test/v1/chat/completions",
        )
    except ValueError as error:
        assert "endpoint is invalid" in str(error)
    else:
        raise AssertionError("unapproved HTTPS answer endpoint must be rejected")


def _service() -> AnswerService:
    return AnswerService(
        {"generation_timeout_seconds": 1, "maximum_retries": 0},
        "test-key",
        "https://answer.example.test/v1/chat/completions",
    )


def _request() -> AnswerRequest:
    return AnswerRequest(
        request_id="request-1",
        trace_id="trace-1",
        query="승인 절차를 알려줘",
        evidence_blocks=[
            {
                "evidence_id": "EV-1",
                "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]",
                "content": "승인이 필요합니다.",
            },
            {
                "evidence_id": "EV-2",
                "citation": "[업무 매뉴얼 v1.0 p.3 예외 절차]",
                "content": "예외 절차를 확인합니다.",
            },
        ],
    )


def _answer(**overrides: object) -> AnswerResponse:
    payload: dict[str, object] = {
        "request_id": "model-request",
        "trace_id": "model-trace",
        "status": "ANSWER",
        "answer": "승인 절차입니다.",
        "sections": [
            {
                "title": "승인",
                "claims": [{"text": "승인이 필요합니다.", "evidence_ids": ["EV-1"]}],
            }
        ],
        "citations": [
            {
                "evidence_id": "EV-1",
                "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]",
            }
        ],
    }
    payload.update(overrides)
    return AnswerResponse.model_validate(payload)


def test_answer_service_accepts_canonical_citation_and_claim_binding() -> None:
    request = _request().model_copy(
        update={
            "evidence_blocks": [
                {
                    **block,
                    "manual_id": "MANUAL-APPROVAL",
                    "title": "업무 매뉴얼",
                    "version": "1.0",
                    "section_title": "승인 절차",
                }
                for block in _request().evidence_blocks
            ]
        }
    )
    result = _service()._validate_response(
        _answer(
            answer_type="COMPARE",
            limitations=["모델이 만든 미검증 제한사항"],
            sections=[
                {
                    "title": "모델이 만든 제목",
                    "article_number": 999,
                    "document_id": "FORGED",
                    "claims": [
                        {"text": "승인이 필요합니다.", "evidence_ids": ["EV-1"]}
                    ],
                }
            ],
        ),
        request,
    )

    assert result.status == "ANSWER"
    assert result.citations[0].evidence_id == "EV-1"
    assert result.sections[0].claims[0].evidence_ids == ["EV-1"]
    assert result.answer == "- 승인이 필요합니다. [EV-1]"
    assert result.summary == ["승인이 필요합니다."]
    assert result.answer_type == "POLICY"
    assert result.limitations == []
    assert result.sections[0].title == "승인 절차"
    assert result.sections[0].document_id == "MANUAL-APPROVAL"
    assert result.sections[0].document_title == "업무 매뉴얼"
    assert result.sections[0].document_version == "1.0"
    assert result.sections[0].article_number is None
    assert result.schema_version == "rag-answer-v1.1"
    assert result.model_version == "gpt-4o-mini"


def test_model_overcitation_is_reduced_to_evidence_containing_exact_claim() -> None:
    service = _service()
    output = GroundedModelOutput.model_validate({
        "status": "ANSWER",
        "sections": [{
            "title": "취소율",
            "claims": [{
                "text": "전체 취소율은 17.59%다.",
                "evidence_ids": ["EV-EXACT", "EV-NUMERIC"],
            }],
        }],
    })

    service._prune_unbound_model_evidence_ids(output, [
        {
            "evidence_id": "EV-EXACT",
            "citation": "[운영 결론]",
            "content": "전체 취소율은 17.59%다.",
        },
        {
            "evidence_id": "EV-NUMERIC",
            "citation": "[취소 표]",
            "content": "합계 | 9,418건 | 1,657건 | 17.59%",
        },
    ])

    assert output.sections[0].claims[0].evidence_ids == ["EV-EXACT"]


def test_model_evidence_uses_canonical_report_rows_without_docx_parser_markers() -> None:
    service = _service()
    prepared = service._model_ready_evidence_blocks([{
        "evidence_id": "EV-REPORT",
        "citation": "[객실 운영보고서]",
        "section_title": "호텔별 취소",
        "content": (
            "[TABLE index=3 style=UNSTYLED]\n"
            "[r1c1 span=1] 주요 취소 사유 | [r1c2 span=1] 건수 | [r1c3 span=1] 비중\n"
            "[r2c1 span=1] 일정 변경 | [r2c2 span=1] 894건 | [r2c3 span=1] 53.95%\n"
            "[/TABLE]"
        ),
    }])

    assert "주요 취소 사유 | 건수 | 비중" in prepared[0]["content"]
    assert "일정 변경 | 894건 | 53.95%" in prepared[0]["content"]
    assert "[r1c1" not in prepared[0]["content"]
    assert "[TABLE" not in prepared[0]["content"]


def test_changed_list_number_is_restored_from_exact_source_without_rewriting_text() -> None:
    service = _service()
    output = GroundedModelOutput.model_validate({
        "status": "ANSWER",
        "sections": [{
            "title": "후속 조치",
            "claims": [{
                "text": "1) 일정 변경 취소에는 일정 변경 상품을 우선 제안한다.",
                "evidence_ids": ["EV-ACTION"],
            }],
        }],
    })
    evidence = [{
        "evidence_id": "EV-ACTION",
        "citation": "[객실팀 판단과 조치]",
        "content": "4) 일정 변경 취소에는 일정 변경 상품을 우선 제안한다.",
    }]

    service._prune_unbound_model_evidence_ids(output, evidence)

    assert output.sections[0].claims[0].text == (
        "4) 일정 변경 취소에는 일정 변경 상품을 우선 제안한다."
    )
    assert output.sections[0].claims[0].evidence_ids == ["EV-ACTION"]


def test_answer_service_rejects_citation_without_bound_claim() -> None:
    result = _service()._validate_response(
        _answer(answer="근거와 연결되지 않은 자유문장", sections=[]),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.citations == []
    assert result.answer != "근거와 연결되지 않은 자유문장"


def test_answer_service_rejects_semantically_unbound_claim_with_valid_id() -> None:
    result = _service()._validate_response(
        _answer(
            sections=[
                {
                    "title": "승인",
                    "claims": [
                        {
                            "text": "근거에 없는 임의의 자유 주장입니다.",
                            "evidence_ids": ["EV-1"],
                        }
                    ],
                }
            ]
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert "원문에서 확인되지" in result.answer


def test_answer_service_rejects_negation_truncation_even_when_substring_matches() -> None:
    request = _request().model_copy(
        update={
            "evidence_blocks": [
                {
                    "evidence_id": "EV-1",
                    "citation": "[환불 매뉴얼 v1.0 p.1]",
                    "content": "환불이 가능하지 않습니다.",
                }
            ]
        }
    )
    result = _service()._validate_response(
        _answer(
            citations=[
                {"evidence_id": "EV-1", "citation": "[환불 매뉴얼 v1.0 p.1]"}
            ],
            sections=[
                {
                    "title": "환불",
                    "claims": [{"text": "환불이 가능", "evidence_ids": ["EV-1"]}],
                }
            ],
        ),
        request,
    )

    assert result.status == "GENERATION_FAILED"
    assert "원문에서 확인되지" in result.answer


def test_answer_service_rejects_punctuation_or_single_character_claim() -> None:
    for text, body in ((".", "본문에 . 문장부호가 있습니다."), ("가", "가 항목입니다.")):
        request = _request().model_copy(
            update={
                "evidence_blocks": [
                    {
                        "evidence_id": "EV-1",
                        "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]",
                        "content": body,
                    }
                ]
            }
        )
        result = _service()._validate_response(
            _answer(
                sections=[
                    {
                        "title": "승인",
                        "claims": [{"text": text, "evidence_ids": ["EV-1"]}],
                    }
                ]
            ),
            request,
        )

        assert result.status == "GENERATION_FAILED"


def test_model_conflict_is_rejected_without_deterministic_version_conflict() -> None:
    result = _service()._validate_response(
        _answer(
            status="POTENTIAL_CONFLICT",
            sections=[],
            citations=[
                {"evidence_id": "EV-1", "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]"},
                {"evidence_id": "EV-2", "citation": "[업무 매뉴얼 v1.0 p.3 예외 절차]"},
            ],
            conflicts=[
                {
                    "description": "서로 무관한 근거를 충돌로 표시합니다.",
                    "evidence_ids": ["EV-1", "EV-2"],
                }
            ],
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.conflicts == []
    assert "재현할 수 없습니다" in result.answer


def test_deterministic_version_conflict_overrides_untrusted_model_status() -> None:
    request = AnswerRequest(
        request_id="request-conflict",
        trace_id="trace-conflict",
        query="전액 환불 가능한가?",
        evidence_blocks=[
            {
                "evidence_id": "EV-OLD",
                "citation": "[환불 매뉴얼 v1.0 p.1]",
                "content": "제3조 구체적인 판단·처리 기준 • 전액 환불이 가능하다",
                "manual_id": "MANUAL-REFUND",
                "title": "환불 매뉴얼",
                "version": "1.0",
            },
            {
                "evidence_id": "EV-NEW",
                "citation": "[환불 매뉴얼 v2.0 p.1]",
                "content": "제3조 구체적인 판단·처리 기준 • 전액 환불은 불가능하다",
                "manual_id": "MANUAL-REFUND",
                "title": "환불 매뉴얼",
                "version": "2.0",
            },
        ],
    )

    result = _service()._validate_response(_answer(), request)

    assert result.status == "POTENTIAL_CONFLICT"
    assert result.sections == []
    assert result.conflicts[0].evidence_ids == ["EV-OLD", "EV-NEW"]
    assert {item.evidence_id for item in result.citations} == {"EV-OLD", "EV-NEW"}
    assert result.answer_type == "POLICY"


def test_answer_service_rejects_extra_unused_citation() -> None:
    result = _service()._validate_response(
        _answer(
            citations=[
                {"evidence_id": "EV-1", "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]"},
                {"evidence_id": "EV-2", "citation": "[업무 매뉴얼 v1.0 p.3 예외 절차]"},
            ]
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.citations == []


def test_claim_must_match_every_referenced_evidence() -> None:
    result = _service()._validate_response(
        _answer(
            citations=[
                {"evidence_id": "EV-1", "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]"},
                {"evidence_id": "EV-2", "citation": "[업무 매뉴얼 v1.0 p.3 예외 절차]"},
            ],
            sections=[
                {
                    "title": "승인",
                    "claims": [
                        {
                            "text": "승인이 필요합니다.",
                            "evidence_ids": ["EV-1", "EV-2"],
                        }
                    ],
                }
            ],
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.citations == []


def test_model_generation_failed_payload_is_sanitized() -> None:
    result = _service()._validate_response(
        _answer(
            status="GENERATION_FAILED",
            answer="모델이 만든 실패 상세",
            summary=["가짜 요약"],
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.answer == "답변 모델이 검증 가능한 결과를 생성하지 못했습니다."
    assert result.summary == []
    assert result.sections == []
    assert result.citations == []


def test_local_comparison_output_satisfies_external_answer_validation() -> None:
    evidence = [
        {
            "evidence_id": f"EV-{index}",
            "manual_id": f"MANUAL-{index}",
            "title": f"매뉴얼 {index}",
            "version": "1.0",
            "section_title": "처리 기준",
            "score": 0.9,
            "citation": f"[매뉴얼 {index} v1.0 p.1]",
            "content": f"제3조 구체적인 판단·처리 기준 • 문서 {index}의 승인 기준을 확인한다.",
        }
        for index in (1, 2)
    ]
    prompt = build_answer_prompt("두 문서 승인 기준을 비교해줘", evidence, "COMPARISON")
    local_payload = EvidenceBoundAnswerComposer().compose(prompt)
    request = AnswerRequest(
        request_id="comparison-request",
        trace_id="comparison-trace",
        query="두 문서 승인 기준을 비교해줘",
        evidence_blocks=evidence,
        intent="COMPARISON",
    )

    result = _service()._validate_response(
        AnswerResponse.model_validate(local_payload),
        request,
    )

    assert result.status == "ANSWER"
    assert result.answer_type == "COMPARE"
    assert len(result.sections) == 2
    assert {citation.evidence_id for citation in result.citations} == {"EV-1", "EV-2"}


def test_answer_service_rejects_forged_citation_text() -> None:
    result = _service()._validate_response(
        _answer(
            citations=[
                {
                    "evidence_id": "EV-1",
                    "citation": "[다른 문서 v9.9 p.999]",
                }
            ],
            limitations=["모델이 만든 미검증 제한사항"],
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.citations == []
    assert result.sections == []
    assert result.limitations == []


def test_answer_service_rejects_claim_id_missing_from_retrieval_or_citations() -> None:
    for evidence_id in ("EV-NOT-RETRIEVED", "EV-2"):
        result = _service()._validate_response(
            _answer(
                sections=[
                    {
                        "title": "승인",
                        "claims": [
                            {
                                "text": "검증되지 않은 주장",
                                "evidence_ids": [evidence_id],
                            }
                        ],
                    }
                ]
            ),
            _request(),
        )

        assert result.status == "GENERATION_FAILED"
        assert result.citations == []


def test_answer_service_rejects_unbound_conflict_ids() -> None:
    result = _service()._validate_response(
        _answer(
            status="POTENTIAL_CONFLICT",
            conflicts=[
                {
                    "description": "근거가 충돌합니다.",
                    "evidence_ids": ["EV-1", "EV-NOT-RETRIEVED"],
                }
            ],
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.conflicts == []


def test_no_evidence_cannot_carry_structured_evidence() -> None:
    result = _service()._validate_response(
        _answer(status="NO_EVIDENCE", answer="근거 없음"),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.citations == []
    assert result.sections == []


def test_context_packer_applies_all_reservations_without_splitting_blocks() -> None:
    service = AnswerService(
        {
            "maximum_context_tokens": 1530,
            "reserved_system_tokens": 700,
            "reserved_question_tokens": 200,
            "maximum_output_tokens": 200,
            "maximum_chunks": 10,
        },
        "test-key",
        "https://answer.example.test/v1/chat/completions",
    )
    blocks = [
        {
            "evidence_id": f"EV-{index}",
            "citation": f"[근거 {index}]",
            "content": "가" * 15,
        }
        for index in range(3)
    ]

    packed = service._context_packer.pack(blocks, serialize_evidence_blocks)

    assert packed.receipt.evidence_token_budget == 430
    assert packed.receipt.used_evidence_tokens <= 430
    assert packed.receipt.packed_evidence_count == 1
    assert packed.receipt.dropped_evidence_count == 2
    assert packed.evidence_blocks[0] is blocks[0]
    assert packed.evidence_blocks[0]["content"] == "가" * 15


def test_context_receipt_and_omission_limitation_are_server_owned() -> None:
    service = _service()
    evidence = [
        {**block, "content": "검증된 본문"}
        for block in _request().evidence_blocks
    ]
    packed = service._context_packer.pack(
        evidence,
        serialize_evidence_blocks,
    )
    receipt = packed.receipt.model_copy(
        update={
            "input_evidence_count": 3,
            "packed_evidence_count": 1,
            "dropped_evidence_count": 2,
        }
    )

    result = service._attach_context_receipt(_answer(limitations=[]), receipt)

    assert result.context_receipt == receipt
    assert result.limitations == [
        "컨텍스트 예산에 따라 검색 근거 3개 중 2개를 제외했습니다."
    ]


def test_invalid_or_exhausted_context_configuration_fails_closed() -> None:
    for override in (
        {"maximum_context_tokens": True},
        {
            "maximum_context_tokens": 100,
            "reserved_system_tokens": 40,
            "reserved_question_tokens": 40,
            "maximum_output_tokens": 40,
        },
    ):
        try:
            AnswerService(
                override,
                "test-key",
                "https://answer.example.test/v1/chat/completions",
            )
        except ValueError as error:
            assert "RAG answer" in str(error)
        else:
            raise AssertionError("invalid context configuration must fail closed")


def test_invalid_transport_timeout_and_retry_settings_fail_closed() -> None:
    for override in (
        {"generation_timeout_seconds": True},
        {"generation_timeout_seconds": 0},
        {"generation_timeout_seconds": 301},
        {"maximum_retries": True},
        {"maximum_retries": -1},
        {"maximum_retries": 4},
        {"maximum_answer_chars": True},
        {"maximum_answer_chars": 0},
        {"maximum_answer_chars": 100001},
        {"maximum_response_bytes": True},
        {"maximum_response_bytes": 1023},
        {"maximum_response_bytes": 4194305},
        {"maximum_points_per_article": True},
        {"maximum_points_per_article": 0},
        {"maximum_points_per_article": 21},
        {"minimum_relevance_score": True},
        {"minimum_relevance_score": -0.01},
        {"minimum_relevance_score": 1.01},
    ):
        try:
            AnswerService(
                override,
                "test-key",
                "https://answer.example.test/v1/chat/completions",
            )
        except ValueError as error:
            assert "RAG answer" in str(error)
        else:
            raise AssertionError("invalid answer transport limits must fail closed")


def test_blank_or_oversized_bound_claim_is_rejected() -> None:
    for claim in ("   ", "x" * 20001):
        result = _service()._validate_response(
            _answer(
                sections=[
                    {
                        "title": "승인",
                        "claims": [{"text": claim, "evidence_ids": ["EV-1"]}],
                    }
                ]
            ),
            _request(),
        )

        assert result.status == "GENERATION_FAILED"
        assert result.sections == []


def test_model_cannot_select_more_than_configured_claim_limit() -> None:
    service = AnswerService(
        {
            "generation_timeout_seconds": 1,
            "maximum_retries": 0,
            "maximum_points_per_article": 1,
        },
        "test-key",
        "https://answer.example.test/v1/chat/completions",
    )
    result = service._validate_response(
        _answer(
            citations=[
                {"evidence_id": "EV-1", "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]"},
                {"evidence_id": "EV-2", "citation": "[업무 매뉴얼 v1.0 p.3 예외 절차]"},
            ],
            sections=[
                {
                    "title": "승인",
                    "claims": [
                        {"text": "승인이 필요합니다.", "evidence_ids": ["EV-1"]},
                        {"text": "예외 절차를 확인합니다.", "evidence_ids": ["EV-2"]},
                    ],
                }
            ],
        ),
        _request(),
    )

    assert result.status == "GENERATION_FAILED"
    assert result.sections == []


def test_multiline_table_claim_is_split_only_when_every_row_binds_to_source() -> None:
    request = AnswerRequest(
        request_id="request-table",
        trace_id="trace-table",
        query="취소 건수가 가장 많은 호텔을 표로 알려줘",
        intent="COMPARISON",
        evidence_blocks=[
            {
                "evidence_id": "EV-TABLE",
                "citation": "[합성 월간 보고서 p.1]",
                "content": "호텔 | 취소 건수 | 비중\n그랜드 | 6265 | 16.54%",
            }
        ],
    )
    result = _service()._validate_response(
        _answer(
            citations=[
                {"evidence_id": "EV-TABLE", "citation": "[합성 월간 보고서 p.1]"}
            ],
            sections=[
                {
                    "title": "호텔별 취소",
                    "claims": [
                        {
                            "text": "호텔 | 취소 건수 | 비중\n그랜드 | 6265 | 16.54%",
                            "evidence_ids": ["EV-TABLE"],
                        }
                    ],
                }
            ],
        ),
        request,
    )

    assert result.status == "ANSWER"
    assert result.summary == [
        "호텔 | 취소 건수 | 비중",
        "그랜드 | 6265 | 16.54%",
    ]


def test_table_column_projection_is_bound_without_allowing_cross_row_mixing() -> None:
    request = AnswerRequest(
        request_id="request-projection",
        trace_id="trace-projection",
        query="취소 건수가 가장 많은 호텔을 알려줘",
        intent="COMPARISON",
        evidence_blocks=[
            {
                "evidence_id": "EV-TABLE",
                "citation": "[합성 월간 보고서 p.1]",
                "content": (
                    "호텔 | 취소 건수 | 비중\n"
                    "더글라스 | 489 | 21.88%\n"
                    "그랜드 | 6265 | 16.54%"
                ),
            }
        ],
    )
    projected = _service()._validate_response(
        _answer(
            citations=[
                {"evidence_id": "EV-TABLE", "citation": "[합성 월간 보고서 p.1]"}
            ],
            sections=[
                {
                    "title": "호텔별 취소",
                    "claims": [
                        {
                            "text": "호텔 | 취소 건수\n그랜드 | 6265",
                            "evidence_ids": ["EV-TABLE"],
                        }
                    ],
                }
            ],
        ),
        request,
    )
    mixed = _service()._validate_response(
        _answer(
            citations=[
                {"evidence_id": "EV-TABLE", "citation": "[합성 월간 보고서 p.1]"}
            ],
            sections=[
                {
                    "title": "호텔별 취소",
                    "claims": [
                        {
                            "text": "호텔 | 취소 건수\n더글라스 | 6265",
                            "evidence_ids": ["EV-TABLE"],
                        }
                    ],
                }
            ],
        ),
        request,
    )

    assert projected.status == "ANSWER"
    assert projected.summary == ["호텔 | 취소 건수", "그랜드 | 6265"]
    assert mixed.status == "GENERATION_FAILED"


def test_question_larger_than_reserved_context_never_reaches_transport() -> None:
    service = AnswerService(
        {
            "maximum_context_tokens": 1600,
            "reserved_system_tokens": 700,
            "reserved_question_tokens": 200,
            "maximum_output_tokens": 400,
        },
        "test-key",
        "https://answer.example.test/v1/chat/completions",
    )
    request = _request().model_copy(update={"query": "장문 질문" * 100})

    result = service.generate(request)

    assert result.status == "GENERATION_FAILED"
    assert "컨텍스트 예약 한도" in result.answer
    assert result.context_receipt is None


def test_incomplete_evidence_fails_before_transport() -> None:
    request = _request().model_copy(
        update={
            "evidence_blocks": [
                {
                    "evidence_id": "EV-1",
                    "citation": "[업무 매뉴얼 v1.0 p.2 승인 절차]",
                }
            ]
        }
    )
    result = _service().generate(request)

    assert result.status == "GENERATION_FAILED"
    assert "모델 입력 계약" in result.answer
    assert result.context_receipt is None


def test_duplicate_evidence_identity_fails_before_transport() -> None:
    block = {
        "evidence_id": "EV-DUPLICATE",
        "citation": "[중복 근거]",
        "content": "검증된 본문",
    }
    request = _request().model_copy(update={"evidence_blocks": [block, dict(block)]})

    result = _service().generate(request)

    assert result.status == "GENERATION_FAILED"
    assert "모델 입력 계약" in result.answer


def test_generate_sends_only_packed_evidence_and_seals_receipt() -> None:
    service = AnswerService(
        {
            "maximum_context_tokens": 1530,
            "reserved_system_tokens": 700,
            "reserved_question_tokens": 200,
            "maximum_output_tokens": 200,
            "maximum_chunks": 10,
            "maximum_retries": 0,
        },
        "test-key",
        "https://answer.example.test/v1/chat/completions",
    )
    request = AnswerRequest(
        request_id="request-packed",
        trace_id="trace-packed",
        query="승인 절차",
        evidence_blocks=[
            {
                "evidence_id": f"EV-{index}",
                "citation": f"[근거 {index}]",
                "content": "가" * 15,
            }
            for index in range(2)
        ],
    )
    model_payload = json.dumps(
        {
            "status": "ANSWER",
            "sections": [
                {
                    "title": "승인",
                    "claims": [{"text": "가" * 15, "evidence_ids": ["EV-0"]}],
                }
            ],
        },
        ensure_ascii=False,
    )
    response_payload = json.dumps(
        {"choices": [{"message": {"content": model_payload}}]},
        ensure_ascii=False,
    ).encode("utf-8")
    sent: dict[str, object] = {}

    class Response:
        is_redirect = False
        headers: dict[str, str] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def iter_bytes(chunk_size: int = 65536):
            assert chunk_size == 65536
            yield response_payload

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def stream(_method: str, _endpoint: str, **kwargs: object) -> Response:
            sent.update(kwargs)
            return Response()

    with patch("src.rag.answer_service.httpx.Client", Client):
        result = service.generate(request)

    outbound = json.loads(bytes(sent["content"]).decode("utf-8"))
    user_prompt = outbound["messages"][1]["content"]
    assert outbound["max_completion_tokens"] == 200
    assert "max_tokens" not in outbound
    assert outbound["response_format"]["type"] == "json_schema"
    assert outbound["response_format"]["json_schema"]["strict"] is True
    schema = outbound["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"status", "sections"}
    assert '"evidence_id":"EV-0"' in user_prompt
    assert '"evidence_id":"EV-1"' not in user_prompt
    assert result.status == "ANSWER"
    assert result.context_receipt is not None
    assert result.context_receipt.packed_evidence_count == 1
    assert result.context_receipt.dropped_evidence_count == 1
    assert any("1개를 제외" in item for item in result.limitations)


def test_generate_rejects_streamed_response_over_configured_byte_limit() -> None:
    service = AnswerService(
        {
            "generation_timeout_seconds": 1,
            "maximum_retries": 0,
            "maximum_response_bytes": 1024,
        },
        "test-key",
        "https://answer.example.test/v1/chat/completions",
    )

    class Response:
        is_redirect = False
        headers: dict[str, str] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def iter_bytes(chunk_size: int = 65536):
            assert chunk_size == 65536
            yield b"x" * 700
            yield b"y" * 700

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def stream(_method: str, _endpoint: str, **_kwargs: object) -> Response:
            return Response()

    with patch("src.rag.answer_service.httpx.Client", Client):
        result = service.generate(_request())

    assert result.status == "GENERATION_FAILED"
    assert result.citations == []
