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
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SqlEvidencePort(Protocol):
    def query(self, question: str, context: IntegrationContext) -> SqlEvidence: ...


class DocumentEvidencePort(Protocol):
    def search(
        self, question: str, context: IntegrationContext
    ) -> tuple[DocumentEvidence, ...]: ...


class ModelPredictionPort(Protocol):
    def predict(self, question: str, context: IntegrationContext) -> dict[str, object]: ...


class EvidenceCoordinator:
    """Coordinates typed evidence only; answer generation is deliberately out of scope."""

    SQL_TOOL = "answervice-sql"
    RAG_TOOL = "internal-manual-search"
    ML_TOOL = "predict-reservation-no-show"

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
        plan = self._router.decide(question)
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
