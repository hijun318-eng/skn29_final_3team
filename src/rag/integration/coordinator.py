"""승인된 route와 Tool Registry 정책에 따라 SQL·문서·ML 근거 호출과 부분 실패를 조정한다."""

from __future__ import annotations

from typing import Protocol

from .contracts import (
    DocumentEvidence,
    IntegrationContext,
    IntegrationResponse,
    IntegrationStatus,
    SqlEvidence,
    ToolRegistration,
    ToolRoute,
)
from .routing import EvidenceRouter


class ToolCallError(RuntimeError):
    """도구 등록·승인·권한·입출력·의존성 실패를 안정된 코드로 상위 계층에 전달한다."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SqlEvidencePort(Protocol):
    """승인된 SQL 실행 경계가 구현해야 할 관측 근거 조회 규약이다."""

    def query(self, question: str, context: IntegrationContext) -> SqlEvidence:
        """질문과 호출 문맥을 받아 출처가 포함된 단일 SQL 근거를 반환한다."""

        ...


class DocumentEvidencePort(Protocol):
    """역할과 기준일이 적용된 문서 검색 구현이 따라야 할 근거 조회 규약이다."""

    def search(
        self, question: str, context: IntegrationContext
    ) -> tuple[DocumentEvidence, ...]:
        """질문과 호출 문맥에 접근 가능한 문서 근거를 점수 순 tuple로 반환한다."""

        ...


class ModelPredictionPort(Protocol):
    """관측 사실과 구분되는 승인 모델 예측 구현의 호출 규약이다."""

    def predict(self, question: str, context: IntegrationContext) -> dict[str, object]:
        """질문과 추적 문맥을 모델 입력으로 해 예측 영수증 사전을 반환한다."""

        ...


class EvidenceCoordinator:
    """답변을 생성하지 않고 승인된 도구에서 typed SQL·문서·예측 근거만 수집한다."""

    SQL_TOOL = "answervice-sql"
    RAG_TOOL = "internal-manual-search"
    ML_TOOL = "ml.predict"

    def __init__(
        self,
        router: EvidenceRouter,
        registrations: dict[str, ToolRegistration],
        sql_port: SqlEvidencePort | None = None,
        document_port: DocumentEvidencePort | None = None,
        model_port: ModelPredictionPort | None = None,
    ) -> None:
        self._router = router
        self._registrations = registrations
        self._sql_port = sql_port
        self._document_port = document_port
        self._model_port = model_port

    def execute(self, question: str, context: IntegrationContext) -> IntegrationResponse:
        """승인 route의 도구를 권한 확인 후 실행하고 전체·부분·차단·실패 상태를 근거와 함께 반환한다."""

        try:
            plan = self._router.decide(
                context.approved_route,
                context.router_decision_id,
            )
        except ValueError as error:
            return self._response(
                context,
                context.approved_route,
                IntegrationStatus.BLOCKED,
                errors={"orchestrator": str(error)},
            )
        routed_context = IntegrationContext(
            **{**context.__dict__, "router_decision_id": plan.decision_id}
        )
        if plan.route == ToolRoute.GENERAL:
            return self._response(routed_context, plan.route, IntegrationStatus.NOT_APPLICABLE)

        sql_items: tuple[SqlEvidence, ...] = ()
        document_items: tuple[DocumentEvidence, ...] = ()
        model_items: tuple[dict[str, object], ...] = ()
        errors: dict[str, str] = {}
        if plan.use_sql:
            try:
                self._authorize(self.SQL_TOOL, context.role)
                if self._sql_port is None:
                    raise ToolCallError("SQL_PORT_NOT_CONFIGURED")
                sql_items = (self._sql_port.query(question, routed_context),)
            except (ToolCallError, TimeoutError) as error:
                errors[self.SQL_TOOL] = self._error_code(error)
        if plan.use_rag:
            try:
                self._authorize(self.RAG_TOOL, context.role)
                if self._document_port is None:
                    raise ToolCallError("RAG_PORT_NOT_CONFIGURED")
                document_items = self._document_port.search(question, routed_context)
                if not document_items:
                    raise ToolCallError("RAG_NO_EVIDENCE")
            except (ToolCallError, TimeoutError) as error:
                errors[self.RAG_TOOL] = self._error_code(error)
        if plan.use_ml:
            try:
                tool_code = plan.ml_tool_code or self.ML_TOOL
                self._authorize(tool_code, context.role)
                if tool_code != self.ML_TOOL or self._model_port is None:
                    raise ToolCallError("ML_PORT_NOT_CONFIGURED")
                model_items = (self._model_port.predict(question, routed_context),)
            except (ToolCallError, TimeoutError) as error:
                errors[plan.ml_tool_code or self.ML_TOOL] = self._error_code(error)

        success_count = int(bool(sql_items)) + int(bool(document_items)) + int(bool(model_items))
        expected_count = int(plan.use_sql) + int(plan.use_rag) + int(plan.use_ml)
        source_partial = any(item.status == "PARTIAL" for item in sql_items)
        if success_count == expected_count and source_partial:
            status = IntegrationStatus.PARTIAL
        elif success_count == expected_count:
            status = IntegrationStatus.SUCCEEDED
        elif success_count:
            status = IntegrationStatus.PARTIAL
        elif any(code.endswith("NOT_APPROVED") or code.endswith("ACCESS_DENIED") for code in errors.values()):
            status = IntegrationStatus.BLOCKED
        else:
            status = IntegrationStatus.FAILED
        warnings = tuple(f"{tool}:{code}" for tool, code in sorted(errors.items()))
        facts = tuple(fact for item in sql_items for fact in item.observed_facts)
        return self._response(
            routed_context,
            plan.route,
            status,
            facts,
            document_items,
            sql_items,
            model_items,
            warnings,
            errors,
        )

    def _authorize(self, tool_code: str, role: str) -> None:
        registration = self._registrations.get(tool_code)
        if registration is None:
            raise ToolCallError("TOOL_NOT_REGISTERED")
        if not registration.enabled or registration.approval_status != "APPROVED":
            raise ToolCallError("TOOL_NOT_APPROVED")
        if not registration.callable_by(role):
            raise ToolCallError("TOOL_ACCESS_DENIED")

    @staticmethod
    def _error_code(error: Exception) -> str:
        return error.code if isinstance(error, ToolCallError) else "TOOL_TIMEOUT"

    @staticmethod
    def _response(
        context: IntegrationContext,
        route: ToolRoute,
        status: IntegrationStatus,
        observed: tuple[dict[str, object], ...] = (),
        documents: tuple[DocumentEvidence, ...] = (),
        sql: tuple[SqlEvidence, ...] = (),
        predictions: tuple[dict[str, object], ...] = (),
        warnings: tuple[str, ...] = (),
        errors: dict[str, str] | None = None,
    ) -> IntegrationResponse:
        return IntegrationResponse(
            request_id=context.request_id,
            trace_id=context.trace_id,
            as_of=context.as_of,
            route=route,
            status=status,
            observed_facts=observed,
            document_facts=documents,
            interpretations=(),
            sql_evidence=sql,
            document_evidence=documents,
            model_predictions=predictions,
            warnings=warnings,
            tool_errors=errors or {},
        )
