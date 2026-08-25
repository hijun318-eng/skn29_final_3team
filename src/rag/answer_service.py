import json
import urllib.request
import urllib.error
from typing import Dict, Any

from .answer_contracts import AnswerRequest, AnswerResponse, Citation
from .answer_prompt import build_answer_prompt
from .llm_failure_diagnostics import LlmFailureDiagnostics


class AnswerService:
    def __init__(self, answer_config: Dict[str, Any], api_key: str, endpoint: str):
        self.config = answer_config
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = self.config.get("generation_timeout_seconds", 20)
        self.max_retries = self.config.get("maximum_retries", 1)

    def generate(self, request: AnswerRequest) -> AnswerResponse:
        if not request.evidence_blocks:
            return AnswerResponse(
                request_id=request.request_id,
                trace_id=request.trace_id,
                status="NO_EVIDENCE",
                answer="검색된 근거가 없습니다.",
            )

        messages = build_answer_prompt(request.query, request.evidence_blocks)

        payload = {
            "model": self.config.get("model", "gpt-4o-mini"),
            "messages": messages,
            "max_tokens": self.config.get("maximum_output_tokens", 700),
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    result_json = json.loads(response.read().decode("utf-8"))

                content = result_json["choices"][0]["message"]["content"]
                if "Selected model is at capacity" in content:
                    last_error = "MODEL_CAPACITY"
                    if attempt < self.max_retries:
                        continue
                    break
                parsed_response = AnswerResponse.model_validate_json(content)

                # Override request/trace IDs to match input
                parsed_response.request_id = request.request_id
                parsed_response.trace_id = request.trace_id

                # Validation rules
                return self._validate_response(parsed_response, request)

            except Exception as error:
                diagnostic = LlmFailureDiagnostics.from_exception(error)
                last_error = diagnostic.code
                if not diagnostic.retryable:
                    break

        # If all retries fail
        return AnswerResponse(
            request_id=request.request_id,
            trace_id=request.trace_id,
            status="GENERATION_FAILED",
            answer=f"응답 생성 실패: {last_error}"
        )

    def _validate_response(self, response: AnswerResponse, request: AnswerRequest) -> AnswerResponse:
        valid_evidence_ids = {block["evidence_id"] for block in request.evidence_blocks}

        if response.status == "ANSWER":
            if not response.citations:
                response.status = "GENERATION_FAILED"
                response.answer = "상태가 ANSWER이지만 인용(citation)이 없습니다."
                return response

            for citation in response.citations:
                if citation.evidence_id not in valid_evidence_ids:
                    response.status = "GENERATION_FAILED"
                    response.answer = f"허용되지 않은 evidence_id 인용: {citation.evidence_id}"
                    return response

        elif response.status == "NO_EVIDENCE":
            # Very basic check to ensure no detailed answer is leaked
            if len(response.answer) > 50:
                response.status = "GENERATION_FAILED"
                response.answer = "상태가 NO_EVIDENCE이지만 답변에 너무 많은 정보가 포함되어 있습니다."

        return response
