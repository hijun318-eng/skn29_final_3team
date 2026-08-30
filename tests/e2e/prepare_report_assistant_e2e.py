"""격리 PostgreSQL DB에 Report Assistant Browser E2E 최소 근거를 준비한다."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid5

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg


E2E_DATABASE = "app_db_report_assistant_e2e"
NAMESPACE = UUID("6b711229-e54e-4f3a-8d0e-525ef9101cf5")


def _deployment_values() -> dict[str, str]:
    """외부 deployment env의 단순 KEY=VALUE만 읽고 secret 원문은 출력하지 않는다."""

    path = Path(os.environ["ANSWERVICE_DEPLOY_ENV_FILE"])
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    required = {
        "APP_ADMIN_USER", "APP_ADMIN_PASSWORD", "APP_MIGRATION_USER",
        "APP_MIGRATION_PASSWORD", "APP_DB_USER", "APP_CATALOG_PUBLISHER_USER",
        "AUTH_PRINCIPALS_HOST_FILE",
    }
    missing = sorted(key for key in required if not values.get(key))
    if missing:
        raise RuntimeError(f"deployment env 필수 항목이 없습니다: {', '.join(missing)}")
    return values


def _analyst_subject(values: dict[str, str]) -> UUID:
    """외부 principal 파일에서 활성 analyst subject 하나만 선택한다."""

    records = json.loads(Path(values["AUTH_PRINCIPALS_HOST_FILE"]).read_text(encoding="utf-8"))
    subjects = [
        UUID(record["subject"])
        for record in records
        if record.get("active") is True and record.get("role") == "analyst"
    ]
    if len(subjects) != 1:
        raise RuntimeError("활성 analyst principal은 정확히 하나여야 합니다.")
    return subjects[0]


def _dsn(user: str, password: str, database: str) -> str:
    """로컬 loopback PostgreSQL DSN을 URL credential escaping과 함께 생성한다."""

    port_text = os.getenv("ANSWERVICE_APP_POSTGRES_PORT", "15432")
    try:
        port = int(port_text)
    except ValueError as error:
        raise RuntimeError("ANSWERVICE_APP_POSTGRES_PORT는 정수여야 합니다.") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("ANSWERVICE_APP_POSTGRES_PORT는 1~65535 범위여야 합니다.")
    return f"postgresql://{quote(user)}:{quote(password)}@127.0.0.1:{port}/{database}"


def _ensure_database(values: dict[str, str]) -> None:
    """기존 App DB를 변경하지 않고 migration role 소유의 E2E DB만 멱등 생성한다."""

    with psycopg.connect(
        _dsn(values["APP_ADMIN_USER"], values["APP_ADMIN_PASSWORD"], "postgres"),
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (E2E_DATABASE,)
        ).fetchone()
        if exists is None:
            migration_role = values["APP_MIGRATION_USER"].replace('"', '""')
            connection.execute(
                f'CREATE DATABASE "{E2E_DATABASE}" OWNER "{migration_role}"'
            )


def _migrate(values: dict[str, str]) -> str:
    """현재 source의 Alembic head를 E2E DB에만 적용하고 실제 목표 revision을 반환한다."""

    backend = Path(__file__).resolve().parents[2] / "app" / "backend"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    config.set_main_option(
        "sqlalchemy.url",
        _dsn(
            values["APP_MIGRATION_USER"],
            values["APP_MIGRATION_PASSWORD"],
            E2E_DATABASE,
        ).replace("%", "%%"),
    )
    migration_roles = {
        "APP_DB_USER": values["APP_DB_USER"],
        "APP_CATALOG_PUBLISHER_USER": values["APP_CATALOG_PUBLISHER_USER"],
    }
    previous = {name: os.environ.get(name) for name in migration_roles}
    os.environ.update(migration_roles)
    try:
        head = ScriptDirectory.from_config(config).get_current_head()
        if head is None:
            raise RuntimeError("Alembic head를 확인할 수 없습니다.")
        command.upgrade(config, "head")
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return head


def _seed(values: dict[str, str], owner: UUID) -> dict[str, str]:
    """승인 Artifact lineage와 이를 참조하는 draft 한 건만 test DB에 멱등 저장한다."""

    ids = {
        name: uuid5(NAMESPACE, name)
        for name in (
            "analysis_definition", "analysis_request", "query_execution",
            "artifact", "report_definition", "report_block",
        )
    }
    query_id = "e2e_query_report_assistant_1"
    snapshot = {"columns": ["month", "revenue"], "rows": [{"month": "2026-08", "revenue": 17000000}]}
    chart = {"chart_type": "bar", "x_field": "month", "y_fields": ["revenue"]}
    revenue_metric = {
        "metric_id": "revenue",
        "result_field": "revenue",
        "label": "Revenue",
        "definition": "승인 매출 합계",
        "unit": "KRW",
    }
    evidence = {
        "artifact_id": str(ids["artifact"]),
        "query_id": query_id,
        "as_of": "2026-08-25",
        "timezone": "Asia/Seoul",
        "period": {"start": "2026-08-01", "end_exclusive": "2026-09-01"},
        "sources": [{
            "name": "E2E synthetic revenue",
            "urn": "urn:li:dataset:(urn:li:dataPlatform:trino,e2e.synthetic_revenue,PROD)",
            "fqn": "e2e.synthetic_revenue",
            "schema_version": "e2e-v1",
            "seed_version": "e2e-v1",
            "synthetic": True,
        }],
        "gates": {"g1": "PASSED", "g2": "PASSED", "g3": "PASSED"},
        "policy_version": "e2e-policy-v1",
        "metrics": [revenue_metric],
        "metric_values": [{**revenue_metric, "value": 17000000}],
    }
    checksum = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with psycopg.connect(
        _dsn(values["APP_MIGRATION_USER"], values["APP_MIGRATION_PASSWORD"], E2E_DATABASE)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO analysis_v1.analysis_definitions
                    (definition_id, version, owner_id, title, question_text_redacted,
                     parameters_json, parameter_hash, semantic_request_json,
                     parameter_schema_json, is_saved)
                VALUES (%s, 1, %s, 'E2E 승인 분석', '월별 승인 매출 요약',
                        '{}'::jsonb, %s, '{}'::jsonb, '{}'::jsonb, false)
                ON CONFLICT (definition_id, version) DO NOTHING
                """,
                (ids["analysis_definition"], owner, "a" * 64),
            )
            cursor.execute(
                """
                INSERT INTO chat.analysis_requests
                    (request_id, request_type, user_id, user_role,
                     question_text_redacted, question_hash, ambiguity_status,
                     sql_policy_version, status, trace_id, started_at, completed_at)
                VALUES (%s, 'CHAT', %s, 'analyst', '월별 승인 매출 요약', %s,
                        'CLEAR', 'e2e-policy-v1', 'SUCCEEDED', %s, now(), now())
                ON CONFLICT (request_id) DO NOTHING
                """,
                (ids["analysis_request"], owner, "b" * 64, uuid5(NAMESPACE, "trace").hex),
            )
            cursor.execute(
                """
                INSERT INTO analysis_v1.analysis_run_links
                    (definition_id, definition_version, request_id, idempotency_key,
                     as_of, timezone_name, parameters_json, parameter_hash)
                VALUES (%s, 1, %s, %s, DATE '2026-08-25', 'Asia/Seoul', '{}'::jsonb, %s)
                ON CONFLICT DO NOTHING
                """,
                (ids["analysis_definition"], ids["analysis_request"], str(ids["analysis_request"]), "c" * 64),
            )
            cursor.execute(
                """
                INSERT INTO query.query_executions
                    (query_execution_id, request_id, attempt_no, generation_mode,
                     generated_sql_redacted, sql_hash, ast_validation_json,
                     join_validation_json, permission_validation_json, explain_json,
                     validation_status, trino_query_id, execution_status, row_count,
                     scan_bytes, result_checksum, source_urns_json, source_cutoff_json)
                VALUES (%s, %s, 1, 'LLM', 'SELECT 1', %s,
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        'ALLOWED', %s, 'SUCCEEDED', 1, 1, %s, '[]'::jsonb, '{}'::jsonb)
                ON CONFLICT (query_execution_id) DO NOTHING
                """,
                (ids["query_execution"], ids["analysis_request"], "d" * 64, query_id, checksum),
            )
            cursor.execute(
                """
                INSERT INTO artifact.analysis_artifacts
                    (artifact_id, request_id, query_execution_id, artifact_type,
                     title, data_snapshot_json, chart_spec_json, narrative_markdown,
                     evidence_json, freshness_status, status, artifact_checksum)
                VALUES (%s, %s, %s, 'TABLE', 'E2E 월별 승인 매출',
                        %s::jsonb, %s::jsonb, '2026년 8월 승인 매출 근거입니다.',
                        %s::jsonb, 'FRESH', 'APPROVED', %s)
                ON CONFLICT (artifact_id) DO UPDATE SET
                    data_snapshot_json = EXCLUDED.data_snapshot_json,
                    chart_spec_json = EXCLUDED.chart_spec_json,
                    narrative_markdown = EXCLUDED.narrative_markdown,
                    evidence_json = EXCLUDED.evidence_json,
                    freshness_status = EXCLUDED.freshness_status,
                    status = EXCLUDED.status,
                    artifact_checksum = EXCLUDED.artifact_checksum
                """,
                (
                    ids["artifact"], ids["analysis_request"], ids["query_execution"],
                    json.dumps(snapshot), json.dumps(chart), json.dumps(evidence), checksum,
                ),
            )
            cursor.execute(
                "INSERT INTO report_v1.report_definitions (definition_id, owner_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (ids["report_definition"], owner),
            )
            cursor.execute(
                """
                INSERT INTO report_v1.report_definition_versions
                    (definition_id, version, status, title, orientation, currency_display_unit)
                VALUES (%s, 1, 'draft', 'Report Assistant E2E 보고서', 'portrait', 'auto')
                ON CONFLICT (definition_id, version) DO NOTHING
                """,
                (ids["report_definition"],),
            )
            cursor.execute(
                """
                INSERT INTO report_v1.report_blocks
                    (definition_id, definition_version, block_id, title, artifact_id,
                     query_id, columns, block_type, x, y, w, h, content,
                     analysis_definition_id, analysis_definition_version)
                VALUES (%s, 1, %s, '승인 매출 차트', %s, %s, 12, 'chart',
                        0, 0, 12, 7, '', %s, 1)
                ON CONFLICT (definition_id, definition_version, block_id) DO NOTHING
                """,
                (
                    ids["report_definition"], ids["report_block"], ids["artifact"],
                    query_id, ids["analysis_definition"],
                ),
            )
    return {name: str(value) for name, value in ids.items()}


def main() -> None:
    """E2E DB 생성·migration·fixture 검증 결과의 비민감 식별자만 출력한다."""

    values = _deployment_values()
    owner = _analyst_subject(values)
    _ensure_database(values)
    head = _migrate(values)
    ids = _seed(values, owner)
    print(f"E2E_DATABASE_READY={E2E_DATABASE}")
    print(f"E2E_MIGRATION_HEAD={head}")
    print(f"E2E_REPORT_DEFINITION_ID={ids['report_definition']}")
    print(f"E2E_ARTIFACT_ID={ids['artifact']}")


if __name__ == "__main__":
    main()
