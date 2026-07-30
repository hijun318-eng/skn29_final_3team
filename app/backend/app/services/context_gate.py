from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Mapping

from app.contracts import ErrorCode, Role
from app.services.context_builder import ContextPackage, ContextPackageBuilder


class G1Decision(str, Enum):
    ALLOW = "ALLOW"
    CLARIFY = "CLARIFY"
    BLOCK = "BLOCK"


class G1ReasonCode(str, Enum):
    ACCESS_DENIED = "ACCESS_DENIED"
    CONTEXT_RELEASE_INACTIVE = "CONTEXT_RELEASE_INACTIVE"
    POLICY_VERSION_INACTIVE = "POLICY_VERSION_INACTIVE"
    TIME_CONTEXT_INVALID = "TIME_CONTEXT_INVALID"
    TEMPLATE_CONTEXT_MISSING = "TEMPLATE_CONTEXT_MISSING"
    TEMPLATE_INACTIVE = "TEMPLATE_INACTIVE"
    ASSET_INACTIVE = "ASSET_INACTIVE"
    COLUMN_INVALID = "COLUMN_INVALID"
    METRIC_CONTEXT_MISSING = "METRIC_CONTEXT_MISSING"
    METRIC_INACTIVE = "METRIC_INACTIVE"
    TIME_FIELD_CONTEXT_MISSING = "TIME_FIELD_CONTEXT_MISSING"
    TIME_FIELD_INVALID = "TIME_FIELD_INVALID"
    DIMENSION_HISTORY_INVALID = "DIMENSION_HISTORY_INVALID"
    JOIN_INACTIVE = "JOIN_INACTIVE"
    PACKAGE_LIMIT_EXCEEDED = "PACKAGE_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class ContextGateEvidence:
    check: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ContextGateRequest:
    package: ContextPackage
    role: Role
    allowed_roles: frozenset[Role]
    entitled_asset_urns: frozenset[str]
    expected_entitlement_hash: str
    active_context_releases: frozenset[str]
    active_policy_versions: frozenset[str]
    active_time_versions: frozenset[str]
    as_of: date
    timezone: str
    supported_timezones: frozenset[str]
    calendar: str
    template_id: str | None
    active_template_ids: frozenset[str]
    normalized_question_ready: bool
    valid_columns_by_urn: Mapping[str, frozenset[str]]
    metric_id: str | None
    active_metric_ids: frozenset[str]
    time_field: str | None
    valid_time_fields_by_urn: Mapping[str, frozenset[str]]
    dimension_history_valid: bool
    join_active: bool


@dataclass(frozen=True)
class ContextGateResult:
    decision: G1Decision
    evidence: tuple[ContextGateEvidence, ...]
    reason_code: G1ReasonCode | None = None
    error_code: ErrorCode | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is G1Decision.ALLOW


class ContextGate:
    """Deterministic G1 gate. It never queries a source DB or changes context."""

    def evaluate(self, request: ContextGateRequest) -> ContextGateResult:
        evidence: list[ContextGateEvidence] = []

        if (
            request.role not in request.allowed_roles
            or request.package.entitlement_hash != request.expected_entitlement_hash
            or any(
                asset.urn not in request.entitled_asset_urns
                for asset in request.package.assets
            )
        ):
            return self._fail(
                evidence,
                "role_entitlement",
                G1Decision.BLOCK,
                G1ReasonCode.ACCESS_DENIED,
                ErrorCode.ACCESS_DENIED,
            )
        self._pass(evidence, "role_entitlement")

        if request.package.context_release not in request.active_context_releases:
            return self._fail(
                evidence,
                "context_release",
                G1Decision.BLOCK,
                G1ReasonCode.CONTEXT_RELEASE_INACTIVE,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "context_release")

        if request.package.policy_version not in request.active_policy_versions:
            return self._fail(
                evidence,
                "policy_version",
                G1Decision.BLOCK,
                G1ReasonCode.POLICY_VERSION_INACTIVE,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "policy_version")

        if (
            request.package.time_version not in request.active_time_versions
            or not isinstance(request.as_of, date)
            or not request.calendar.strip()
            or request.timezone not in request.supported_timezones
        ):
            return self._fail(
                evidence,
                "time_context",
                G1Decision.CLARIFY,
                G1ReasonCode.TIME_CONTEXT_INVALID,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "time_context")

        if request.template_id is None and not request.normalized_question_ready:
            return self._fail(
                evidence,
                "template_or_question",
                G1Decision.CLARIFY,
                G1ReasonCode.TEMPLATE_CONTEXT_MISSING,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        if (
            request.template_id is not None
            and request.template_id not in request.active_template_ids
        ):
            return self._fail(
                evidence,
                "template_or_question",
                G1Decision.BLOCK,
                G1ReasonCode.TEMPLATE_INACTIVE,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "template_or_question")

        for asset in request.package.assets:
            valid_columns = request.valid_columns_by_urn.get(asset.urn)
            if valid_columns is None:
                return self._fail(
                    evidence,
                    "asset",
                    G1Decision.BLOCK,
                    G1ReasonCode.ASSET_INACTIVE,
                    ErrorCode.ACCESS_DENIED,
                )
            if not set(asset.columns).issubset(valid_columns):
                return self._fail(
                    evidence,
                    "column",
                    G1Decision.BLOCK,
                    G1ReasonCode.COLUMN_INVALID,
                    ErrorCode.CONTEXT_INCOMPLETE,
                )
        self._pass(evidence, "asset_column")

        if request.metric_id is None:
            return self._fail(
                evidence,
                "metric",
                G1Decision.CLARIFY,
                G1ReasonCode.METRIC_CONTEXT_MISSING,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        if request.metric_id not in request.active_metric_ids:
            return self._fail(
                evidence,
                "metric",
                G1Decision.BLOCK,
                G1ReasonCode.METRIC_INACTIVE,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "metric")

        if request.time_field is None:
            return self._fail(
                evidence,
                "time_field",
                G1Decision.CLARIFY,
                G1ReasonCode.TIME_FIELD_CONTEXT_MISSING,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        if not any(
            request.time_field in request.valid_time_fields_by_urn.get(asset.urn, ())
            for asset in request.package.assets
        ):
            return self._fail(
                evidence,
                "time_field",
                G1Decision.BLOCK,
                G1ReasonCode.TIME_FIELD_INVALID,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "time_field")

        if not request.dimension_history_valid:
            return self._fail(
                evidence,
                "dimension_history",
                G1Decision.BLOCK,
                G1ReasonCode.DIMENSION_HISTORY_INVALID,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "dimension_history")

        if not request.join_active:
            return self._fail(
                evidence,
                "join",
                G1Decision.BLOCK,
                G1ReasonCode.JOIN_INACTIVE,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "join")

        actual_columns = sum(len(asset.columns) for asset in request.package.assets)
        if (
            len(request.package.assets) > ContextPackageBuilder.MAX_DATASETS
            or actual_columns > ContextPackageBuilder.MAX_COLUMNS
            or request.package.token_count > request.package.token_limit
            or request.package.token_count > ContextPackageBuilder.MAX_TOKENS
        ):
            return self._fail(
                evidence,
                "package_limit",
                G1Decision.CLARIFY,
                G1ReasonCode.PACKAGE_LIMIT_EXCEEDED,
                ErrorCode.CONTEXT_INCOMPLETE,
            )
        self._pass(evidence, "package_limit")

        return ContextGateResult(
            decision=G1Decision.ALLOW,
            evidence=tuple(evidence),
        )

    @staticmethod
    def _pass(evidence: list[ContextGateEvidence], check: str) -> None:
        evidence.append(ContextGateEvidence(check, True, "PASS"))

    @staticmethod
    def _fail(
        evidence: list[ContextGateEvidence],
        check: str,
        decision: G1Decision,
        reason_code: G1ReasonCode,
        error_code: ErrorCode,
    ) -> ContextGateResult:
        evidence.append(ContextGateEvidence(check, False, reason_code.value))
        return ContextGateResult(
            decision=decision,
            evidence=tuple(evidence),
            reason_code=reason_code,
            error_code=error_code,
        )
