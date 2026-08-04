from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.contracts import (
    AnalysisRequest,
    ErrorCode,
    PeriodEvidence,
    RequestContext,
    SourceReference,
)
from app.ports.data_platform import DataPlatformAdapter
from app.services.context_builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextMetric,
    ContextPackage,
    ContextPackageBuilder,
    ContextRequiredFilter,
)


@lru_cache(maxsize=1)
def _metric_glossary() -> dict[str, tuple[str, ...]]:
    path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "ai"
        / "contracts"
        / "metric_glossary.i5.v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(payload.get("version"), str) or not isinstance(metrics, dict):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "R3 metric glossary 계약을 확인할 수 없습니다.",
        )
    glossary = {
        str(metric_id): tuple(str(alias) for alias in aliases)
        for metric_id, aliases in metrics.items()
        if isinstance(aliases, list) and aliases
    }
    if len(glossary) != len(metrics):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "R3 metric glossary alias 계약을 확인할 수 없습니다.",
        )
    return glossary


def _normalize_question(payload: dict[str, object]) -> dict[str, object]:
    from src.ai.node1 import normalize_question

    return normalize_question(payload)


class PipelineSupport:
    """Context, G2, 식별자 생성처럼 상태 전이와 무관한 순수 보조 로직."""

    MAX_QUERY_ROWS = 1_000
    MAX_RESULT_ROWS = 100
    MAX_RESULT_COLUMNS = 20
    MAX_RESULT_CELLS = 2_000

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        context_builder: ContextPackageBuilder,
    ) -> None:
        self._adapter = adapter
        self._context_builder = context_builder

    def build_context(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
    ) -> ContextPackage:
        items = tuple(
            ContextAsset(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                columns=tuple(
                    str(column["name"])
                    for column in self._adapter.get_asset_schema(
                        str(asset["urn"])
                    )["columns"]
                ),
                join_ids=tuple(str(join_id) for join_id in asset.get("join_ids", ())),
                metrics=tuple(
                    ContextMetric(
                        id=str(metric["id"]),
                        asset_fqn=str(metric["asset_fqn"]),
                        field=str(metric["field"]),
                        aggregation=str(metric["aggregation"]),
                        time_field=str(metric["time_field"]),
                        required_filters=tuple(
                            ContextRequiredFilter(
                                field=str(item["field"]),
                                operator=str(item["operator"]),
                                value=item["value"],
                            )
                            for item in metric["required_filters"]
                        ),
                    )
                    for metric in asset.get("metrics", ())
                ),
                metric_registry_required="metrics" in asset,
            )
            for asset in assets
        )
        request = ContextBuildRequest(
            context_release="context-v1",
            policy_version="policy-v1",
            time_version=context.as_of.isoformat(),
            entitlement_hash=hashlib.sha256(
                f"{context.user_id}:{context.role.value}".encode()
            ).hexdigest(),
            assets=items,
            token_count=max(1, len(payload.question.split()) * 4),
            model_context_tokens=24_000,
        )
        return self._context_builder.build(
            request,
            frozenset(item.urn for item in items),
        )

    @staticmethod
    def select_metric(
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], str]:
        if not any("metrics" in asset for asset in assets):
            return assets, payload.question

        candidates = [
            metric
            for asset in assets
            for metric in asset.get("metrics", ())
            if isinstance(metric, dict) and isinstance(metric.get("id"), str)
        ]
        candidate_ids = [str(metric["id"]) for metric in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "동일한 metric id를 중복 선택할 수 없습니다.",
            )
        glossary = _metric_glossary()
        business_terms = {
            metric_id: {"kind": "metric", "aliases": list(glossary[metric_id])}
            for metric_id in candidate_ids
            if metric_id in glossary
        }
        try:
            timezone = ZoneInfo(context.timezone)
        except ZoneInfoNotFoundError as error:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context timezone을 확인할 수 없습니다.",
            ) from error
        as_of = datetime.combine(context.as_of, time.min, timezone).isoformat()
        normalized = _normalize_question(
            {
                "question": payload.question,
                "role_hint": context.role.value,
                "as_of": as_of,
                "timezone": context.timezone,
                "calendar_id": "gregorian-kr",
                "allowed_routes": ["general", "template"],
                "business_terms": business_terms,
            }
        )
        selected = normalized.get("selected_metric_id")
        if not isinstance(selected, str) or selected not in candidate_ids:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "질문에서 권한이 있는 승인 metric 하나를 확인할 수 없습니다.",
            )
        selected_assets = []
        for asset in assets:
            item = dict(asset)
            if "metrics" in item:
                item["metrics"] = tuple(
                    metric
                    for metric in item.get("metrics", ())
                    if isinstance(metric, dict) and metric.get("id") == selected
                )
            selected_assets.append(item)
        return selected_assets, str(normalized["normalized_question"])

    @staticmethod
    def g1_error(scenario: str) -> tuple[ErrorCode, str] | None:
        return {
            "clarification": (
                ErrorCode.CONTEXT_INCOMPLETE,
                "분석 기간 또는 기준을 보완해 주세요.",
            ),
            "access_denied": (
                ErrorCode.ACCESS_DENIED,
                "요청한 데이터 범위에 접근할 수 없습니다.",
            ),
            "inactive_context": (
                ErrorCode.CONTEXT_INCOMPLETE,
                "활성 Context 또는 정책 버전을 찾을 수 없습니다.",
            ),
        }.get(scenario)

    @staticmethod
    def g2_violation(
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        if not isinstance(plan, dict):
            return "MODEL_SCHEMA_INVALID"
        sql = str(plan.get("sql", "")).strip()
        normalized = sql.lower()
        forbidden = {
            "insert",
            "update",
            "delete",
            "drop",
            "alter",
            "create",
            "grant",
            "revoke",
            "call",
            "merge",
            "execute",
            "prepare",
        }
        tokens = set(re.findall(r"[a-z_]+", normalized))
        if (
            re.match(r"select\b", normalized) is None
            or ";" in normalized
            or tokens.intersection(forbidden)
            or {"system", "information_schema"}.intersection(tokens)
            or re.search(
                r"\b(?:current_date|current_timestamp|localtime|now)\s*(?:\(\s*\))?",
                normalized,
            )
        ):
            return "UNSAFE_SQL"
        parameters = plan.get("parameters", {})
        if not isinstance(parameters, dict):
            return "PARAMETERS_INVALID"
        limit = re.search(r"\blimit\s+(\d+)\s*$", normalized)
        if limit is None or int(limit.group(1)) > PipelineSupport.MAX_QUERY_ROWS:
            return "RESOURCE_POLICY_MISSING"
        allowed = {item.fqn for item in package.assets}
        references = plan.get("references")
        if not isinstance(references, list) or not references:
            return "REFERENCE_MISSING"
        referenced = {str(item.get("fqn")) for item in references}
        if not referenced.issubset(allowed):
            return "REFERENCE_OUTSIDE_CONTEXT"
        expected_metric_ids = {metric.id for metric in package.metrics}
        has_metric_references = any("metric_ids" in item for item in references)
        if expected_metric_ids and has_metric_references:
            referenced_metric_ids = {
                str(metric_id)
                for item in references
                for metric_id in item.get("metric_ids", ())
            }
            if referenced_metric_ids != expected_metric_ids:
                return "METRIC_REFERENCE_MISMATCH"
        queried = {
            table.strip('"').lower()
            for table in re.findall(
                r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)",
                sql,
                flags=re.IGNORECASE,
            )
        }
        if queried != {item.lower() for item in referenced}:
            return "SQL_REFERENCE_MISMATCH"
        if len({table.split(".", 1)[0] for table in queried}) > 1:
            referenced_join_ids = {
                str(join_id)
                for item in references
                for join_id in item.get("join_ids", ())
            }
            if (
                not package.approved_join_ids
                or referenced_join_ids != set(package.approved_join_ids)
                or queried != {item.fqn.lower() for item in package.assets}
            ):
                return "UNAPPROVED_JOIN"
        if any(
            not PipelineSupport._required_filter_matches(normalized, item)
            for metric in package.metrics
            for item in metric.required_filters
        ):
            return "METRIC_FILTER_MISSING"
        return None

    @staticmethod
    def _required_filter_matches(sql: str, required: ContextRequiredFilter) -> bool:
        if required.operator != "eq":
            return False
        where = re.search(
            r"\bwhere\b(.+?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if where is None or re.search(r"\bor\b", where.group(1), re.IGNORECASE):
            return False
        field = re.escape(required.field.lower())
        values = re.findall(
            rf"(?<![a-z0-9_])(?:[a-z_][a-z0-9_]*\.)?{field}\s*=\s*"
            r"(?:'([^']*)'|(true|false))(?![a-z0-9_])",
            where.group(1),
            flags=re.IGNORECASE,
        )
        expected = str(required.value).lower()
        normalized = [string.lower() if string else boolean.lower() for string, boolean in values]
        return bool(normalized) and all(value == expected for value in normalized)

    @staticmethod
    def model_plan_violation(plan: object) -> str | None:
        if not isinstance(plan, dict):
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("sql"), str) or not plan["sql"].strip():
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("references"), list):
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("parameters", {}), dict):
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("model_version"), str):
            return "MODEL_SCHEMA_INVALID"
        return None

    @classmethod
    def g3_violation(cls, query: dict[str, object]) -> str | None:
        if not query.get("evidence_complete"):
            return "EVIDENCE_INCOMPLETE"
        rows = query.get("rows")
        scalar_types = (str, int, float, bool, type(None))
        if (
            not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
            or any(
                not isinstance(value, scalar_types)
                for row in rows
                for value in row.values()
            )
        ):
            return "RESULT_SCHEMA_INVALID"
        filters = query.get("filters", {})
        sampling = query.get("sampling", {})
        masking = query.get("masking", {})
        if (
            not isinstance(filters, dict)
            or any(not isinstance(value, scalar_types) for value in filters.values())
            or not isinstance(sampling, dict)
            or not isinstance(masking, dict)
        ):
            return "EVIDENCE_SCHEMA_INVALID"
        if query.get("zero_result_suspicious"):
            return "SUSPICIOUS_EMPTY_RESULT"
        column_count = max((len(row) for row in rows), default=0)
        if (
            len(rows) > cls.MAX_RESULT_ROWS
            or column_count > cls.MAX_RESULT_COLUMNS
            or len(rows) * column_count > cls.MAX_RESULT_CELLS
        ):
            return "RESULT_RANGE_EXCEEDED"
        return None

    @staticmethod
    def period(as_of: date) -> PeriodEvidence:
        return PeriodEvidence(
            start=as_of.replace(day=1),
            end_exclusive=as_of,
        )

    @staticmethod
    def gate_token(package: ContextPackage, sql: str) -> str:
        return hashlib.sha256(
            f"{package.package_hash}:{sql}".encode()
        ).hexdigest()

    @staticmethod
    def artifact_id(
        trace_id: str,
        query_id: str,
        context_hash: str,
    ) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"{trace_id}:{query_id}:{context_hash}",
        )

    @staticmethod
    def sources(
        assets: list[dict[str, object]],
    ) -> tuple[SourceReference, ...]:
        return tuple(
            SourceReference(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                name=str(asset["name"]),
                schema_version=str(asset["schema_version"]),
                seed_version=str(asset["seed_version"]),
            )
            for asset in assets
        )
