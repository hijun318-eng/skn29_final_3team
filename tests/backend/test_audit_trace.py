from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from sys import path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.audit_repository import PostgresAuditRepository, _uuid  # noqa: E402
from app.api import audit_router as audit_api  # noqa: E402
from app.audit_contracts import AuditTraceResponse  # noqa: E402
from app.contracts import RequestContext, Role  # noqa: E402


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _context(role: Role = Role.HOTEL_ANALYST) -> RequestContext:
    return RequestContext(
        user_id=uuid4(), role=role, as_of=date(2026, 8, 12), trace_id="audit-test"
    )


def _safe_row() -> dict:
    request_id, owner_id, definition_id, artifact_id = (uuid4() for _ in range(4))
    return {
        "request_id": request_id,
        "user_id": owner_id,
        "user_role": "hotel_analyst",
        "request_type": "CHAT",
        "status": "SUCCEEDED",
        "error_type": None,
        "trace_id": "trace-1",
        "started_at": NOW,
        "completed_at": NOW,
        "definition_id": definition_id,
        "definition_version": 1,
        "definition_status": "approved",
        "context_release_id": None,
        "release_key": None,
        "release_version": None,
        "release_hash": None,
        "context_package_id": None,
        "package_hash": None,
        "sql_policy_version": "policy-v1",
        "model_version_id": None,
        "model_role": None,
        "model_name": None,
        "model_revision": None,
        "runtime_name": None,
        "trino_query_id": "query-1",
        "generation_mode": "TEMPLATE",
        "validation_status": "ALLOWED",
        "execution_status": "SUCCEEDED",
        "duration_ms": 12,
        "artifact_id": artifact_id,
        "artifact_type": "COMPOSITE",
        "freshness_status": "FRESH",
        "artifact_status": "APPROVED",
        "artifact_checksum": "a" * 64,
        # 저장소 행에 존재하더라도 응답 조립 대상이 될 수 없는 민감 payload.
        "generated_sql_redacted": "SELECT secret",
        "parameters_json": {"guest": "secret"},
        "data_snapshot_json": {"secret": True},
    }


def test_detail_returns_linked_metadata_without_sql_parameters_or_result_payload():
    detail = PostgresAuditRepository._detail(
        _safe_row(),
        [{"sequence": 1, "from_status": None, "to_status": "RECEIVED", "created_at": NOW}],
        [],
    )
    payload = AuditTraceResponse.model_validate(detail).model_dump(mode="json")
    serialized = str(payload)

    assert payload["query"]["query_id"] == "query-1"
    assert payload["artifact"]["artifact_id"]
    for forbidden in ("SELECT secret", "parameters_json", "data_snapshot_json", "guest"):
        assert forbidden not in serialized


def test_repository_search_binds_owner_and_reads_only_safe_summary_columns():
    owner_id, request_id = uuid4(), uuid4()
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value = []
    with patch("app.adapters.audit_repository._engine", return_value=engine):
        PostgresAuditRepository("postgresql://runtime", owner_id).search(request_id)

    statement, parameters = connection.execute.call_args.args
    sql = str(statement)
    assert parameters == {"owner_id": owner_id, "request_id": request_id}
    assert "r.user_id = :owner_id" in sql
    for forbidden in ("question_text", "generated_sql", "parameters_json", "data_snapshot_json"):
        assert forbidden not in sql


class _AuditRepository:
    def __init__(self, item: dict) -> None:
        self.item = item
        self.searched = None

    def search(self, request_id=None):
        self.searched = request_id
        return [{key: self.item[key] for key in (
            "request_id", "user_id", "user_role", "request_type", "status",
            "error_type", "trace_id", "started_at", "completed_at",
        )}]

    def get(self, request_id):
        if str(request_id) != str(self.item["request_id"]):
            raise KeyError("감사 Trace를 찾을 수 없습니다.")
        return PostgresAuditRepository._detail(self.item, [], [])


@pytest.mark.parametrize("role", list(Role))
def test_search_and_detail_keep_every_role_in_authenticated_owner_scope(role: Role):
    context = _context(role)
    row = _safe_row()
    row["user_id"] = context.user_id
    row["user_role"] = role.value
    repository = _AuditRepository(row)
    with patch.object(audit_api, "_repository", return_value=repository):
        searched = audit_api.search_audit_requests(context, str(row["request_id"]))
        detail = audit_api.get_audit_trace(str(row["request_id"]), context)

    assert repository.searched == str(row["request_id"])
    assert searched["items"][0]["user_id"] == context.user_id
    assert detail["user_id"] == context.user_id


def test_invalid_or_foreign_request_is_not_disclosed():
    context = _context()
    repository = _AuditRepository(_safe_row())
    with patch.object(audit_api, "_repository", return_value=repository):
        with pytest.raises(HTTPException) as missing:
            audit_api.get_audit_trace(str(uuid4()), context)
    assert missing.value.status_code == 404

    with pytest.raises(ValueError):
        _uuid("not-a-uuid")
