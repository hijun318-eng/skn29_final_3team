"""OpenAI-compatible answer endpoint를 호출하고 evidence 인용 계약을 재검증한다."""

import json
import unicodedata
from typing import Dict, Any
from urllib.parse import urlsplit

import httpx

from .answer_contracts import (
    AnswerClaim,
    AnswerContextReceipt,
    AnswerRequest,
    AnswerResponse,
    Citation,
    Conflict,
    GroundedModelOutput,
)
from .answer_context import AnswerContextPacker
from .answer_prompt import build_answer_prompt, serialize_evidence_blocks
from .answer_safety import AnswerSafetySettings, EvidenceSafetyGate
from .llm_failure_diagnostics import LlmFailureDiagnostics
from .manual_article_formatter import ManualArticleFormatter
from .report_evidence_formatter import ReportEvidenceFormatter


_ANSWER_TYPE_BY_INTENT = {
    "PROCESS": "PROCEDURE",
    "IMMEDIATE_ACTION": "IMMEDIATE",
    "DECISION_CRITERIA": "CRITERIA",
    "REGULATION_CHECK": "POLICY",
    "COMPARISON": "COMPARE",
    "SUMMARY": "SUMMARY",
}


class AnswerService:
    """redirect 차단·timeout·제한 retry로 근거 답변을 생성하고 허용 ID만 통과시킨다."""

    def __init__(self, answer_config: Dict[str, Any], api_key: str, endpoint: str):
        parsed_endpoint = urlsplit(endpoint)
        allowed_http_hosts = answer_config.get("allowed_http_hosts", [])
        allowed_https_hosts = answer_config.get("allowed_https_hosts")
        if (
            parsed_endpoint.scheme not in {"http", "https"}
            or not parsed_endpoint.hostname
            or parsed_endpoint.username
            or parsed_endpoint.password
            or not isinstance(allowed_http_hosts, list)
            or any(
                not isinstance(host, str)
                or not host.strip()
                or host != host.strip().lower()
                for host in allowed_http_hosts
            )
            or len(allowed_http_hosts) != len(set(allowed_http_hosts))
            or (
                allowed_https_hosts is not None
                and (
                    not isinstance(allowed_https_hosts, list)
                    or any(
                        not isinstance(host, str)
                        or not host.strip()
                        or host != host.strip().lower()
                        for host in allowed_https_hosts
                    )
                    or len(allowed_https_hosts) != len(set(allowed_https_hosts))
                )
            )
            or (
                parsed_endpoint.scheme == "http"
                and parsed_endpoint.hostname.lower() not in allowed_http_hosts
            )
            or (
                parsed_endpoint.scheme == "https"
                and allowed_https_hosts is not None
                and parsed_endpoint.hostname.lower() not in allowed_https_hosts
            )
        ):
            raise ValueError("RAG answer endpoint is invalid")
        if not api_key.strip():
            raise ValueError("RAG answer API key is missing")
        self.config = answer_config
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = self._bounded_timeout(
            self.config.get("generation_timeout_seconds", 20)
        )
        self.max_retries = self._bounded_retries(
            self.config.get("maximum_retries", 1)
        )
        self.maximum_answer_chars = self._bounded_answer_chars(
            self.config.get("maximum_answer_chars", 20000)
        )
        self.maximum_response_bytes = self._bounded_response_bytes(
            self.config.get("maximum_response_bytes", 1048576)
        )
        self.maximum_claims = self._bounded_claims(
            self.config.get("maximum_points_per_article", 6)
        )
        relevance_score = self._bounded_relevance_score(
            self.config.get("minimum_relevance_score", 0.18)
        )
        self._conflict_gate = EvidenceSafetyGate(
            AnswerSafetySettings(
                minimum_relevance_score=relevance_score,
                maximum_answer_chars=self.maximum_answer_chars,
            )
        )
        self._manual_formatter = ManualArticleFormatter()
        self._report_formatter = ReportEvidenceFormatter()
        self._context_packer = AnswerContextPacker(answer_config)

    @staticmethod
    def _bounded_timeout(value: Any) -> float:
        """유한한 0.1~300초 generation timeout만 허용해 무기한 또는 즉시 실패를 막는다."""

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0.1 <= float(value) <= 300.0
        ):
            raise ValueError("RAG answer generation timeout must be between 0.1 and 300 seconds")
        return float(value)

    @staticmethod
    def _bounded_retries(value: Any) -> int:
        """재시도 폭증을 막기 위해 0~3 범위의 정수만 answer transport에 허용한다."""

        if type(value) is not int or not 0 <= value <= 3:
            raise ValueError("RAG answer maximum retries must be between 0 and 3")
        return value

    @staticmethod
    def _bounded_answer_chars(value: Any) -> int:
        """모델 구조 답변의 전체 claim·conflict 문자 한도를 1~100,000자로 제한한다."""

        if type(value) is not int or not 1 <= value <= 100000:
            raise ValueError("RAG answer character limit must be between 1 and 100000")
        return value

    @staticmethod
    def _bounded_response_bytes(value: Any) -> int:
        """응답 본문 상한을 1KiB~4MiB 정수로 고정해 메모리 고갈을 방지한다."""

        if type(value) is not int or not 1024 <= value <= 4 * 1024 * 1024:
            raise ValueError("RAG answer response limit must be between 1024 and 4194304 bytes")
        return value

    @staticmethod
    def _bounded_claims(value: Any) -> int:
        """외부 모델이 선택할 수 있는 전체 claim 수를 1~20개로 제한한다."""

        if type(value) is not int or not 1 <= value <= 20:
            raise ValueError("RAG answer claim limit must be between 1 and 20")
        return value

    @staticmethod
    def _bounded_relevance_score(value: Any) -> float:
        """결정론적 충돌 detector가 사용할 관련성 점수를 유한한 0~1 값으로 제한한다."""

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= float(value) <= 1
        ):
            raise ValueError("RAG answer relevance score must be between 0 and 1")
        return float(value)

    def generate(self, request: AnswerRequest) -> AnswerResponse:
        """evidence가 있으면 모델 JSON을 생성·검증하고 실패를 typed status로 축약한다."""

        if not request.evidence_blocks:
            return AnswerResponse(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status="NO_EVIDENCE",
                answer="검색된 근거가 없습니다.",
            )

        try:
            self._context_packer.validate_reserved_messages(
                build_answer_prompt(request.query, [], request.intent)
            )
        except ValueError:
            return AnswerResponse(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status="GENERATION_FAILED",
                answer="질문 또는 답변 지시가 모델 컨텍스트 예약 한도를 초과했습니다.",
            )

        try:
            packed_context = self._context_packer.pack(
                request.evidence_blocks,
                serialize_evidence_blocks,
            )
        except (TypeError, ValueError):
            return AnswerResponse(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status="GENERATION_FAILED",
                answer="검색 근거의 모델 입력 계약이 올바르지 않습니다.",
            )
        packed_request = request.model_copy(
            update={"evidence_blocks": list(packed_context.evidence_blocks)}
        )
        if not packed_request.evidence_blocks:
            return self._attach_context_receipt(
                AnswerResponse(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status="NO_EVIDENCE",
                    answer="컨텍스트 예산 안에 포함할 수 있는 완전한 검색 근거가 없습니다.",
                ),
                packed_context.receipt,
            )

        messages = build_answer_prompt(
            request.query,
            packed_request.evidence_blocks,
            request.intent,
        )

        response_schema = GroundedModelOutput.model_json_schema()
        payload = {
            "model": self.config.get("model", "gpt-4o-mini"),
            "messages": messages,
            "max_completion_tokens": self.config.get("maximum_output_tokens", 700),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "answervice_grounded_rag_answer",
                    "strict": True,
                    "schema": response_schema,
                },
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(float(self.timeout)),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    with client.stream(
                        "POST",
                        self.endpoint,
                        content=json.dumps(payload).encode("utf-8"),
                        headers=headers,
                    ) as response:
                        if response.is_redirect:
                            raise ValueError("RAG answer endpoint redirect is not allowed")
                        response.raise_for_status()
                        result_json = self._read_bounded_json_response(response)

                content = result_json["choices"][0]["message"]["content"]
                if "Selected model is at capacity" in content:
                    last_error = "MODEL_CAPACITY"
                    if attempt < self.max_retries:
                        continue
                    break
                model_output = GroundedModelOutput.model_validate_json(content)
                source_citations = {
                    str(block.get("evidence_id") or ""): str(block.get("citation") or "")
                    for block in packed_request.evidence_blocks
                }
                referenced_ids = list(dict.fromkeys(
                    evidence_id
                    for section in model_output.sections
                    for claim in section.claims
                    for evidence_id in claim.evidence_ids
                ))
                parsed_response = AnswerResponse(
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    status=model_output.status,
                    answer="",
                    sections=[section.model_dump() for section in model_output.sections],
                    citations=[
                        Citation(
                            evidence_id=evidence_id,
                            citation=source_citations.get(evidence_id, ""),
                        )
                        for evidence_id in referenced_ids
                    ],
                )

                # Override request/trace IDs to match input
                parsed_response.request_id = request.request_id
                parsed_response.trace_id = request.trace_id

                # Validation rules
                validated = self._validate_response(parsed_response, packed_request)
                return self._attach_context_receipt(
                    validated,
                    packed_context.receipt,
                )

            except Exception as error:
                diagnostic = LlmFailureDiagnostics.from_exception(error)
                last_error = diagnostic.code
                if not diagnostic.retryable:
                    break

        # If all retries fail
        return self._attach_context_receipt(
            AnswerResponse(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status="GENERATION_FAILED",
                answer="현재 답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            ),
            packed_context.receipt,
        )

    def _read_bounded_json_response(self, response: httpx.Response) -> dict[str, Any]:
        """Content-Length와 실제 디코딩 바이트를 모두 검사해 JSON 응답을 제한 내에서 읽는다."""

        declared_length = response.headers.get("content-length")
        if declared_length is not None:
            try:
                parsed_length = int(declared_length)
            except ValueError as error:
                raise ValueError("RAG answer response Content-Length is invalid") from error
            if parsed_length < 0 or parsed_length > self.maximum_response_bytes:
                raise ValueError("RAG answer response exceeds the configured byte limit")

        body = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            if len(chunk) > self.maximum_response_bytes - len(body):
                raise ValueError("RAG answer response exceeds the configured byte limit")
            body.extend(chunk)
        if not body:
            raise ValueError("RAG answer response is empty")

        decoded = json.loads(bytes(body).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("RAG answer response root must be a JSON object")
        return decoded

    @staticmethod
    def _attach_context_receipt(
        response: AnswerResponse,
        receipt: AnswerContextReceipt,
    ) -> AnswerResponse:
        """서버 계산 예산 영수증과 근거 제외 사실을 모델 출력과 무관하게 응답에 봉인한다."""

        response.context_receipt = receipt
        if receipt.dropped_evidence_count:
            limitation = (
                "컨텍스트 예산에 따라 검색 근거 "
                f"{receipt.input_evidence_count}개 중 "
                f"{receipt.dropped_evidence_count}개를 제외했습니다."
            )
            if limitation not in response.limitations:
                response.limitations.append(limitation)
        return response

    def _validate_response(
        self,
        response: AnswerResponse,
        request: AnswerRequest,
    ) -> AnswerResponse:
        """모든 모델 인용·주장·충돌 ID를 retrieval evidence와 exact bind한다."""

        response.schema_version = "rag-answer-v1.1"
        response.model_version = str(self.config.get("model") or "gpt-4o-mini")
        response.answer_type = _ANSWER_TYPE_BY_INTENT[request.intent]
        evidence_citations: dict[str, str] = {}
        evidence_bodies: dict[str, str] = {}
        evidence_segments: dict[str, frozenset[str]] = {}
        for block in request.evidence_blocks:
            evidence_id = block.get("evidence_id")
            citation = block.get("citation")
            body = block.get("content") or block.get("text") or block.get("snippet")
            if (
                not isinstance(evidence_id, str)
                or not evidence_id.strip()
                or not isinstance(citation, str)
                or not citation.strip()
                or not isinstance(body, str)
                or not body.strip()
                or evidence_id in evidence_citations
            ):
                return self._generation_failed(
                    response,
                    "검색 근거의 인용 계약이 올바르지 않습니다.",
                )
            evidence_citations[evidence_id] = citation
            evidence_bodies[evidence_id] = body
            evidence_segments[evidence_id] = self._canonical_claim_segments(block, body)

        verified_conflicts = self._verified_conflicts(request, evidence_bodies)
        if verified_conflicts:
            return self._seal_verified_conflicts(
                response,
                verified_conflicts,
                evidence_citations,
            )

        if response.status == "ANSWER":
            if not response.citations:
                return self._generation_failed(
                    response,
                    "상태가 ANSWER이지만 인용(citation)이 없습니다.",
                )

            cited_ids: set[str] = set()
            for citation in response.citations:
                expected_citation = evidence_citations.get(citation.evidence_id)
                if (
                    expected_citation is None
                    or citation.evidence_id in cited_ids
                    or citation.citation != expected_citation
                ):
                    return self._generation_failed(
                        response,
                        "모델 인용이 검색 근거와 일치하지 않습니다.",
                    )
                cited_ids.add(citation.evidence_id)

            self._split_canonically_bound_lines(response, evidence_segments)
            referenced_ids: list[str] = []
            for section in response.sections:
                for claim in section.claims:
                    referenced_ids.extend(claim.evidence_ids)
            bound_texts = [
                claim.text
                for section in response.sections
                for claim in section.claims
            ]
            if (
                any(not text.strip() for text in bound_texts)
                or len(bound_texts) > self.maximum_claims
                or sum(len(text) for text in bound_texts) > self.maximum_answer_chars
            ):
                return self._generation_failed(
                    response,
                    "근거 연결 문장의 길이 계약이 올바르지 않습니다.",
                )
            if any(
                not self._claim_is_canonically_bound(
                    claim.text,
                    claim.evidence_ids,
                    evidence_segments,
                )
                for section in response.sections
                for claim in section.claims
            ):
                return self._generation_failed(
                    response,
                    "근거 연결 문장이 인용된 원문에서 확인되지 않습니다.",
                )
            if (
                not response.sections
                or response.conflicts
                or any(not section.claims for section in response.sections)
            ):
                return self._generation_failed(
                    response,
                    "답변 상태에 필요한 근거 연결 주장이 없습니다.",
                )
            if not referenced_ids or cited_ids != set(referenced_ids):
                return self._generation_failed(
                    response,
                    "인용 목록과 실제 주장·충돌 근거가 정확히 일치하지 않습니다.",
                )
            if any(
                evidence_id not in evidence_citations
                or evidence_id not in cited_ids
                for evidence_id in referenced_ids
            ):
                return self._generation_failed(
                    response,
                    "주장 또는 충돌 근거가 검증된 인용 목록과 일치하지 않습니다.",
                )
            self._bind_section_metadata(response, request.evidence_blocks)
            response.answer = self._render_bound_answer(response)
            response.summary = list(
                dict.fromkeys(
                    claim.text
                    for section in response.sections
                    for claim in section.claims
                )
            )
            response.limitations = []

        elif response.status == "POTENTIAL_CONFLICT":
            return self._generation_failed(
                response,
                "모델의 충돌 판정을 서버 근거에서 재현할 수 없습니다.",
            )
        elif response.status == "NO_EVIDENCE":
            if (
                len(response.answer) > 50
                or response.citations
                or response.sections
                or response.conflicts
            ):
                return self._generation_failed(
                    response,
                    "상태가 NO_EVIDENCE이지만 근거 기반 상세 내용이 포함되어 있습니다.",
                )
            response.answer = "검색된 근거가 없습니다."
            response.summary = []
            response.limitations = []
        elif response.status == "GENERATION_FAILED":
            return self._generation_failed(
                response,
                "답변 모델이 검증 가능한 결과를 생성하지 못했습니다.",
            )

        return response

    @classmethod
    def _split_canonically_bound_lines(
        cls,
        response: AnswerResponse,
        evidence_segments: dict[str, frozenset[str]],
    ) -> None:
        """모델이 하나로 묶은 원문 표·불릿 행을 검증 가능한 claim 단위로 분리한다."""

        for section in response.sections:
            normalized: list[AnswerClaim] = []
            for claim in section.claims:
                lines = [line.strip() for line in claim.text.splitlines() if line.strip()]
                if len(lines) > 1 and all(
                    cls._claim_is_canonically_bound(
                        line,
                        claim.evidence_ids,
                        evidence_segments,
                    )
                    for line in lines
                ):
                    normalized.extend(
                        AnswerClaim(text=line, evidence_ids=list(claim.evidence_ids))
                        for line in lines
                    )
                elif cls._table_projection_is_bound(
                    lines,
                    claim.evidence_ids,
                    evidence_segments,
                ):
                    for evidence_id in claim.evidence_ids:
                        evidence_segments[evidence_id] = frozenset(
                            set(evidence_segments[evidence_id])
                            | {cls._normalize_claim_segment(line) for line in lines}
                        )
                    normalized.extend(
                        AnswerClaim(text=line, evidence_ids=list(claim.evidence_ids))
                        for line in lines
                    )
                else:
                    normalized.append(claim)
            section.claims = normalized

    @classmethod
    def _table_projection_is_bound(
        cls,
        lines: list[str],
        evidence_ids: list[str],
        evidence_segments: dict[str, frozenset[str]],
    ) -> bool:
        """표 열 투영이 각 원문 행의 동일 column 조합인지 검증하고 행 혼합을 거부한다."""

        projected_rows = [cls._table_cells(line) for line in lines]
        if (
            len(lines) < 2
            or not evidence_ids
            or any(row is None for row in projected_rows)
            or len({len(row) for row in projected_rows if row is not None}) != 1
            or any(character.isdigit() for cell in projected_rows[0] for character in cell)
        ):
            return False
        projected = [row for row in projected_rows if row is not None]
        for evidence_id in evidence_ids:
            if evidence_id not in evidence_segments:
                return False
            source_rows = [
                cells
                for segment in evidence_segments[evidence_id]
                if (cells := cls._table_cells(segment)) is not None
            ]
            if not any(
                all(
                    any(
                        len(source_row) > max(indices)
                        and [source_row[index] for index in indices] == projected_row
                        for source_row in source_rows
                    )
                    for projected_row in projected[1:]
                )
                for source_header in source_rows
                if (indices := cls._subsequence_indices(source_header, projected[0]))
            ):
                return False
        return True

    @staticmethod
    def _table_cells(line: str) -> list[str] | None:
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        return cells if len(cells) >= 2 else None

    @staticmethod
    def _subsequence_indices(source: list[str], selected: list[str]) -> list[int]:
        indices: list[int] = []
        cursor = 0
        for cell in selected:
            try:
                index = source.index(cell, cursor)
            except ValueError:
                return []
            indices.append(index)
            cursor = index + 1
        return indices

    @staticmethod
    def _claim_is_canonically_bound(
        text: str,
        evidence_ids: list[str],
        evidence_segments: dict[str, frozenset[str]],
    ) -> bool:
        """claim이 인용 원문의 전체 문장·불릿·표 행과 정확히 같은지 확인한다."""

        normalized_claim = AnswerService._normalize_claim_segment(text)
        if sum(character.isalnum() for character in normalized_claim) < 2:
            return False
        return (
            bool(evidence_ids)
            and all(evidence_id in evidence_segments for evidence_id in evidence_ids)
            and all(
                normalized_claim in evidence_segments[evidence_id]
                for evidence_id in evidence_ids
            )
        )

    def _canonical_claim_segments(
        self,
        block: dict[str, Any],
        body: str,
    ) -> frozenset[str]:
        """manual·report parser가 결정론적으로 분리한 원문 segment를 정규화해 봉인한다."""

        candidates = [
            *self._manual_formatter.claim_segments(
                body,
                str(block.get("section_title") or ""),
            ),
            *self._report_formatter.claim_segments(body),
        ]
        return frozenset(
            normalized
            for candidate in candidates
            if (normalized := self._normalize_claim_segment(candidate))
            and sum(character.isalnum() for character in normalized) >= 2
        )

    @staticmethod
    def _normalize_claim_segment(text: str) -> str:
        """Unicode와 연속 공백만 정규화하고 부정어·문장부호 등 의미 경계는 보존한다."""

        return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()

    def _verified_conflicts(
        self,
        request: AnswerRequest,
        evidence_bodies: dict[str, str],
    ) -> list[Conflict]:
        """같은 문서의 활성 version 간 반대 polarity를 서버 규칙으로 다시 계산한다."""

        normalized_evidence = [
            {
                **block,
                "body": evidence_bodies[str(block["evidence_id"])],
            }
            for block in request.evidence_blocks
        ]
        answer_type = _ANSWER_TYPE_BY_INTENT[request.intent]
        target_numbers = self._manual_formatter.target_numbers(
            request.query,
            answer_type,
        )
        groups = self._conflict_gate.ranked_groups(
            normalized_evidence,
            request.query,
            target_numbers,
        )
        return self._conflict_gate.detect_conflicts(
            groups,
            request.query,
            answer_type,
            self._manual_formatter,
        )

    def _seal_verified_conflicts(
        self,
        response: AnswerResponse,
        conflicts: list[Conflict],
        evidence_citations: dict[str, str],
    ) -> AnswerResponse:
        """결정론적 detector 결과와 서버 citation만으로 잠재 충돌 응답을 재구성한다."""

        evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for conflict in conflicts
                for evidence_id in conflict.evidence_ids
            )
        )
        if (
            any(evidence_id not in evidence_citations for evidence_id in evidence_ids)
            or sum(len(conflict.description) for conflict in conflicts)
            > self.maximum_answer_chars
        ):
            return self._generation_failed(
                response,
                "서버 충돌 판정의 근거 계약이 올바르지 않습니다.",
            )
        response.status = "POTENTIAL_CONFLICT"
        response.sections = []
        response.conflicts = conflicts
        response.citations = [
            Citation(
                evidence_id=evidence_id,
                citation=evidence_citations[evidence_id],
            )
            for evidence_id in evidence_ids
        ]
        response.summary = []
        response.limitations = ["상충하는 문서 버전을 임의로 선택하지 않았습니다."]
        response.answer = self._render_bound_answer(response)
        return response

    @staticmethod
    def _bind_section_metadata(
        response: AnswerResponse,
        evidence_blocks: list[dict[str, Any]],
    ) -> None:
        """section의 문서·영역 표시값을 claim이 참조한 서버 evidence metadata로 덮어쓴다."""

        by_id = {
            str(block["evidence_id"]): block
            for block in evidence_blocks
        }
        for section in response.sections:
            referenced = list(
                dict.fromkeys(
                    evidence_id
                    for claim in section.claims
                    for evidence_id in claim.evidence_ids
                )
            )
            blocks = [by_id[evidence_id] for evidence_id in referenced]

            def single_value(*names: str) -> str:
                values = {
                    str(next((block.get(name) for name in names if block.get(name)), ""))
                    for block in blocks
                }
                values.discard("")
                return values.pop() if len(values) == 1 else ""

            section.document_id = single_value("document_id", "manual_id")
            section.document_title = single_value("title")
            section.document_version = single_value("version")
            section.title = single_value("section_title") or "근거 기반 답변"
            section.article_number = None

    @staticmethod
    def _render_bound_answer(response: AnswerResponse) -> str:
        """검증된 claim·conflict만 evidence ID 표식과 함께 사용자 답변으로 재구성한다."""

        lines: list[str] = []
        for section in response.sections:
            for claim in section.claims:
                evidence = ", ".join(claim.evidence_ids)
                lines.append(f"- {claim.text} [{evidence}]")
        for conflict in response.conflicts:
            evidence = ", ".join(conflict.evidence_ids)
            lines.append(f"- 충돌: {conflict.description} [{evidence}]")
        return "\n".join(lines)

    @staticmethod
    def _generation_failed(
        response: AnswerResponse,
        message: str,
    ) -> AnswerResponse:
        """검증 실패 응답에서 미검증 구조를 제거해 downstream 노출을 차단한다."""

        response.status = "GENERATION_FAILED"
        response.answer = message
        response.summary = []
        response.sections = []
        response.citations = []
        response.conflicts = []
        response.limitations = []
        response.context_receipt = None
        return response
