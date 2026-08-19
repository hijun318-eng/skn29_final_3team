"""Trino 행 schema·checksum·sampling·masking을 승인 AST와 runtime metric에 대조하고, 통과 결과에만 기간 근거·capability·결정론적 artifact ID를 부여한다."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.contracts import PeriodEvidence, SourceReference
from app.query_capability import issue_query_capability
from app.services.context_builder import ContextPackage


class PipelineResultValidator:
    """Trino 결과의 행·열·cell 한도, scalar 타입과 G3 evidence 일치를 검증한다.

    모델 서술을 신뢰하지 않고 실제 columns/rows와 context metric을 대조하며, 빈 aggregate는
    승인된 aggregate shape일 때만 결정론적으로 정규화한다. 위반 시 capability를 발급하지
    않고 구체적인 G3 violation을 반환한다.
    """
    MAX_RESULT_ROWS = 1_000
    MAX_RESULT_COLUMNS = 50
    MAX_RESULT_CELLS = 20_000

    @staticmethod
    def result_value_type(value: object) -> str:
        """Trino 결과 scalar를 증거 계약의 제한된 타입 이름으로 분류한다.

        ``bool``을 정수보다 먼저 판별하고 허용되지 않은 객체는 직렬화하지 않고
        ``unsupported``로 반환해 G3 결과 schema 검사가 명시적으로 차단하도록 한다.
        """
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
        """Trino 행·컬럼 결과에서 값 타입, 행 수, null 여부의 결정론적 메타데이터를 만든다."""
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
        """실행 결과와 승인된 AST·runtime context가 일치하는지 G3에서 검증한다.

        행 schema, checksum, sampling, masking, 식별자 노출, 크기 상한을 순서대로 검사해 첫
        위반 code를 반환하고, 모든 증거가 맞을 때만 ``None``을 반환한다. 잘못된 값을
        보정하지 않아 미검증 결과가 성공 응답이나 보고서로 승격되지 않게 한다.
        """
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

    @classmethod
    def normalize_empty_aggregate(
        cls,
        query: dict[str, object],
        package: ContextPackage,
    ) -> dict[str, object]:
        """empty aggregate 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다."""
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
        """runtime time 규칙이 지목한 바인딩으로 반개방 기간 근거를 구성한다.

        로컬 날짜나 질문 문구를 대체값으로 쓰지 않는다. 이름 또는 문자열 값이 없으면
        ``ValueError``를, ISO 날짜가 잘못되면 파서 오류를 전파한다.
        """
        contracts = getattr(package, "runtime_contracts", None) or {}
        time_rules = contracts.get("time_rules") or {}
        bindings = {item.name: item.value for item in package.parameter_bindings}
        start = bindings.get(time_rules.get("start_parameter"))
        end = bindings.get(time_rules.get("end_parameter"))
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError("Runtime period evidence is incomplete")
        return PeriodEvidence(start=date.fromisoformat(start), end_exclusive=date.fromisoformat(end))

    @staticmethod
    def gate_token(package: ContextPackage, sql: str) -> str:
        """승인 context hash와 정규 SQL에 묶인 일회성 실행 capability를 발급한다.

        실행 adapter가 같은 context·SQL 조합의 G2 통과 사실을 검증하도록 해 검증 뒤 SQL
        치환이나 다른 package에서의 token 재사용을 차단한다.
        """
        return issue_query_capability(package.package_hash, sql)

    @staticmethod
    def artifact_id(request_id: str, query_id: str, context_hash: str) -> UUID:
        """요청·Trino query·context snapshot 조합의 결정론적 UUID를 반환한다.

        세 식별자 중 하나라도 달라지면 다른 artifact가 되어 재시도 시 동일 실행만 멱등하게 연결된다.
        """
        return uuid5(NAMESPACE_URL, f"{request_id}:{query_id}:{context_hash}")

    @staticmethod
    def sources(assets: list[dict[str, object]]) -> tuple[SourceReference, ...]:
        """runtime discovery asset을 응답용 typed source lineage로 변환한다.

        URN·FQN·schema/data release를 원본 순서대로 보존하고, synthetic 표시는 실제 boolean일
        때만 전달한다. 필수 필드 누락이나 계약 위반은 숨기지 않고 생성 예외로 실패시킨다.
        """
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
        """runtime 계약이 요구한 기간·필터 parameter와 실제 바인딩 값을 추출한다.

        time 또는 metric filter 이름이 package binding에 없으면 ``ValueError``로 차단한다.
        반환값은 실행 sink가 저장할 최소 근거이며 질문에서 기간이나 필터를 재추론하지 않는다.
        """
        contracts = getattr(package, "runtime_contracts", None) or {}
        time_rules = contracts.get("time_rules") or {}
        bindings = {item.name: item.value for item in package.parameter_bindings}
        start_name = time_rules.get("start_parameter")
        end_name = time_rules.get("end_parameter")
        if start_name not in bindings or end_name not in bindings:
            raise ValueError("Runtime period bindings are incomplete")
        filter_names = {
            item["parameter"]
            for metric in contracts.get("metric_rules", ())
            for item in metric.get("required_filters", ())
        }
        if not filter_names.issubset(bindings):
            raise ValueError("Runtime filter bindings are incomplete")
        return {
            "period": {
                "start": bindings[start_name],
                "end_exclusive": bindings[end_name],
            },
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
