"""Trino 쿼리 실행 결과 및 G3 거버넌스 검증기(PipelineResultValidator) 모듈.

[핵심 목적]
Trino 등 실행 엔진에서 반환된 쿼리 결과(행, 컬럼, 셀)에 대해:
1. 결과 크기 한도(최대 1,000행, 50열, 20,000셀) 검사
2. AST 프로젝션 컬럼과 실제 반환 컬럼 스키마/체크섬 엄격 대조
3. 마스킹되지 않은 민감 식별자(Unmasked Identifier) 노출 차단
4. 의심스러운 빈 집계 결과 정규화(`normalize_empty_aggregate`)
5. 결정론적 아티팩트 ID(`uuid5`) 및 실행 Capability 토큰 발급
을 수행하여 계약으로 확인 가능한 결과 범위를 검증합니다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.contracts import PeriodEvidence, SnapshotEvidence, SourceReference
from app.query_capability import issue_query_capability
from app.services.context.builder import ContextPackage


class PipelineResultValidator:
    """쿼리 실행 결과의 거버넌스 무결성(G3)을 검증하는 정적 검증기 클래스."""

    MAX_RESULT_ROWS = 1_000
    MAX_RESULT_COLUMNS = 50
    MAX_RESULT_CELLS = 20_000

    @staticmethod
    def result_value_type(value: object) -> str:
        """Trino 결과 스칼라 값의 타입을 표준 문자열로 매핑합니다."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        return "unsupported"

    @classmethod
    def result_metadata(
        cls,
        rows: list[dict[str, object]],
        columns: tuple[str, ...],
    ) -> dict[str, object]:
        """행/컬럼 데이터로부터 컬럼별 타입, 행 수, SHA-256 체크섬 메타데이터를 계산합니다."""
        typed_columns = []
        for name in columns:
            kinds = {
                cls.result_value_type(row.get(name))
                for row in rows
                if row.get(name) is not None
            }
            if kinds <= {"integer", "number"} and "number" in kinds:
                kinds = {"number"}
            value_type = next(iter(kinds)) if len(kinds) == 1 else (
                "null" if not kinds else "mixed"
            )
            typed_columns.append({"name": name, "type": value_type})
        canonical_rows = json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "columns": typed_columns,
            "row_count": len(rows),
            "checksum": hashlib.sha256(canonical_rows.encode("utf-8")).hexdigest(),
        }

    @classmethod
    def g3_violation(
        cls,
        query: dict[str, object],
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        """실행 결과가 승인된 계획 및 ContextPackage 규칙을 충족하는지 G3 게이트 검증을 수행합니다."""
        if not query.get("evidence_complete"):
            return "EVIDENCE_INCOMPLETE"
        if not isinstance(query.get("query_id"), str) or not query["query_id"]:
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
        evidence = plan.get("ast_evidence")
        aliases = evidence.get("projection_aliases") if isinstance(evidence, dict) else None
        if (
            not isinstance(aliases, list)
            or not aliases
            or any(not isinstance(item, str) for item in aliases)
            or len(aliases) != len(set(aliases))
        ):
            return "RESULT_CONTRACT_INVALID"
        expected_columns = tuple(aliases)
        if any(tuple(row) != expected_columns for row in rows):
            return "RESULT_SCHEMA_INVALID"
        if cls._unmasked_identifier(expected_columns, query, package):
            return "SENSITIVE_RESULT_BLOCKED"
        if query.get("result_metadata") != cls.result_metadata(rows, expected_columns):
            return "EVIDENCE_MISMATCH"
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
        returned_rows = sampling.get("returned_rows")
        total_rows = sampling.get("total_rows")
        sampling_applied = sampling.get("applied")
        if (
            not isinstance(sampling_applied, bool)
            or not isinstance(returned_rows, int)
            or isinstance(returned_rows, bool)
            or not isinstance(total_rows, int)
            or isinstance(total_rows, bool)
            or returned_rows != len(rows)
            or total_rows < returned_rows
            or (not sampling_applied and total_rows != returned_rows)
        ):
            return "EVIDENCE_MISMATCH"
        masking_applied = masking.get("applied")
        masking_fields = masking.get("fields")
        if (
            not isinstance(masking_applied, bool)
            or not isinstance(masking_fields, (list, tuple))
            or any(not isinstance(field, str) for field in masking_fields)
            or len(masking_fields) != len(set(masking_fields))
            or not set(masking_fields).issubset(expected_columns)
            or masking_applied != bool(masking_fields)
        ):
            return "MASKING_EVIDENCE_INVALID"
        if not rows or query.get("zero_result_suspicious"):
            return "EMPTY_RESULT"
        if cls._ratio_value_violation(rows, package):
            return "EVIDENCE_MISMATCH"
        column_count = max((len(row) for row in rows), default=0)
        if (
            len(rows) > cls.MAX_RESULT_ROWS
            or column_count > cls.MAX_RESULT_COLUMNS
            or len(rows) * column_count > cls.MAX_RESULT_CELLS
        ):
            return "RESULT_RANGE_EXCEEDED"
        return None

    @staticmethod
    def _ratio_value_violation(
        rows: list[dict[str, object]],
        package: ContextPackage,
    ) -> bool:
        """Reject ratio cells that disagree with their governed operands.

        G2 verifies the SQL AST, while this G3 check proves the returned value
        is numerically consistent with the numerator and denominator in each
        shaped row. A small relative tolerance covers DOUBLE serialization only.
        """

        by_id = {metric.id: metric for metric in package.metrics}
        for metric in package.metrics:
            if metric.reduction != "ratio":
                continue
            numerator = by_id.get(metric.numerator_metric_id)
            denominator = by_id.get(metric.denominator_metric_id)
            if numerator is None or denominator is None:
                return True
            for row in rows:
                try:
                    numerator_value = Decimal(str(row[numerator.result_field]))
                    denominator_value = Decimal(str(row[denominator.result_field]))
                    actual_raw = row[metric.result_field]
                    if denominator_value == 0:
                        if actual_raw is not None:
                            return True
                        continue
                    if actual_raw is None:
                        return True
                    actual = Decimal(str(actual_raw))
                    expected = numerator_value / denominator_value
                except (InvalidOperation, KeyError, TypeError, ValueError):
                    return True
                tolerance = max(Decimal("1e-12"), abs(expected) * Decimal("1e-9"))
                if abs(actual - expected) > tolerance:
                    return True
        return False

    @classmethod
    def normalize_empty_aggregate(
        cls,
        query: dict[str, object],
        package: ContextPackage,
    ) -> dict[str, object]:
        """단일 행 집계 결과가 모두 null인 경우 빈 행 목록으로 정규화합니다."""
        rows = query.get("rows")
        result_fields = {metric.result_field for metric in package.metrics}
        if not isinstance(rows, list) or len(rows) != 1 or not result_fields:
            return query
        row = rows[0]
        selected = result_fields.intersection(row) if isinstance(row, dict) else set()
        if not selected or any(row[field] is not None for field in selected):
            return query
        normalized = dict(query)
        normalized["rows"] = []
        normalized["zero_result_suspicious"] = True
        metadata = query.get("result_metadata")
        columns = tuple(
            str(item["name"])
            for item in metadata.get("columns", ())
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ) if isinstance(metadata, dict) else tuple(row)
        normalized["result_metadata"] = cls.result_metadata([], columns)
        sampling = dict(query.get("sampling") or {})
        sampling.update(returned_rows=0, total_rows=0)
        normalized["sampling"] = sampling
        return normalized

    @staticmethod
    def period(package: ContextPackage) -> PeriodEvidence:
        """ContextPackage의 시간 파라미터 바인딩으로부터 PeriodEvidence 객체를 생성합니다."""
        contracts = getattr(package, "runtime_contracts", None) or {}
        time_rules = contracts.get("time_rules") or {}
        bindings = {item.name: item.value for item in package.parameter_bindings}
        start = bindings.get(time_rules.get("start_parameter"))
        end = bindings.get(time_rules.get("end_parameter"))
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError("런타임 기간 증거 데이터가 불완전합니다.")
        return PeriodEvidence(start=date.fromisoformat(start), end_exclusive=date.fromisoformat(end))

    @staticmethod
    def snapshot(package: ContextPackage) -> SnapshotEvidence:
        """ContextPackage의 서버 소유 기준일 binding에서 snapshot evidence를 만든다."""

        contracts = getattr(package, "runtime_contracts", None) or {}
        time_rules = contracts.get("time_rules") or {}
        if (
            time_rules.get("mode") != "latest_snapshot"
            or time_rules.get("selection") != "max_source_value_lt_as_of"
        ):
            raise ValueError("런타임 최신 스냅샷 계약이 불완전합니다.")
        bindings = {item.name: item for item in package.parameter_bindings}
        binding = bindings.get(time_rules.get("as_of_parameter"))
        if (
            binding is None
            or binding.value_type != "date"
            or not isinstance(binding.value, str)
        ):
            raise ValueError("런타임 스냅샷 기준일 binding이 불완전합니다.")
        return SnapshotEvidence(
            cutoff=date.fromisoformat(binding.value),
            selection="max_source_value_lt_as_of",
        )

    @staticmethod
    def gate_token(package: ContextPackage, sql: str) -> str:
        """G2 검증을 통과한 SQL과 ContextPackage 해시에 결속된 실행 capability 토큰을 발급합니다."""
        return issue_query_capability(package.package_hash, sql)

    @staticmethod
    def artifact_id(request_id: str, query_id: str, context_hash: str) -> UUID:
        """요청 ID, 쿼리 ID, 컨텍스트 해시로부터 결정론적 UUID(v5)를 생성합니다."""
        return uuid5(NAMESPACE_URL, f"{request_id}:{query_id}:{context_hash}")

    @staticmethod
    def sources(assets: list[dict[str, object]]) -> tuple[SourceReference, ...]:
        """자산 메타데이터 목록을 SourceReference 튜플로 변환합니다."""
        return tuple(
            SourceReference(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                name=str(asset["name"]),
                schema_version=str(asset["schema_version"]),
                seed_version=str(asset["seed_version"]),
                synthetic=asset["synthetic"] if isinstance(asset.get("synthetic"), bool) else None,
            )
            for asset in assets
        )

    @staticmethod
    def execution_evidence(package: ContextPackage) -> dict[str, dict[str, object]]:
        """실행 시 적용된 기간 및 필터 바인딩 증거 딕셔너리를 추출합니다."""
        contracts = getattr(package, "runtime_contracts", None) or {}
        time_rules = contracts.get("time_rules") or {}
        bindings = {item.name: item.value for item in package.parameter_bindings}
        mode = str(time_rules.get("mode") or "range")
        if mode == "latest_snapshot":
            snapshot = PipelineResultValidator.snapshot(package)
            time_evidence: dict[str, object] = {
                "snapshot": snapshot.model_dump(mode="json")
            }
        elif mode == "range":
            start_name = time_rules.get("start_parameter")
            end_name = time_rules.get("end_parameter")
            if start_name not in bindings or end_name not in bindings:
                raise ValueError("런타임 기간 파라미터 바인딩이 불완전합니다.")
            time_evidence = {
                "period": {
                    "start": bindings[start_name],
                    "end_exclusive": bindings[end_name],
                }
            }
        else:
            raise ValueError("지원되지 않는 런타임 시간 선택 mode입니다.")
        filter_rules = [
            item
            for metric in contracts.get("metric_rules", ())
            for item in metric.get("required_filters", ())
        ]
        filter_rules.extend(contracts.get("filter_rules", ()) or ())
        filter_names = {item["parameter"] for item in filter_rules}
        if not filter_names.issubset(bindings):
            raise ValueError("런타임 필터 파라미터 바인딩이 불완전합니다.")
        return {
            **time_evidence,
            "filters": {name: bindings[name] for name in sorted(filter_names)},
        }

    @staticmethod
    def _unmasked_identifier(
        expected_columns: tuple[str, ...],
        query: dict[str, object],
        package: ContextPackage,
    ) -> bool:
        contracts = getattr(package, "runtime_contracts", None) or {}
        schema = contracts.get("schema_context") or {}
        time_rules = contracts.get("time_rules") or {}
        time_cols = {
            item["field"]["column"]
            for item in time_rules.get("fields", ())
            if isinstance(item.get("field"), dict) and "column" in item["field"]
        }
        dimension_cols = {
            dim["column"]
            for metric in contracts.get("metric_rules", ())
            for dim in metric.get("dimensions", ())
            if isinstance(dim, dict) and "column" in dim
        } | {
            key
            for asset in schema.get("assets", ())
            for key in (asset.get("grain") or {}).get("keys", ())
            if isinstance(key, str)
        }
        identifiers = {
            column["name"]
            for asset in schema.get("assets", ())
            for column in asset.get("columns", ())
            if column.get("role") == "identifier"
            and column["name"] not in time_cols
            and column["name"] not in dimension_cols
        }
        exposed = identifiers.intersection(expected_columns)
        masking = query.get("masking") or {}
        masked = set(masking.get("fields", ())) if isinstance(masking, dict) else set()
        unmasked = exposed - masked
        return bool(unmasked)
