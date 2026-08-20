"""운영 D0/D1 verifier가 불변 release 계약을 일반적으로 해석하는지 검증한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "infrastructure" / "database" / "scripts"
RELEASES = ROOT / "infrastructure" / "database" / "releases"
sys.path.insert(0, str(SCRIPTS))

from inspect_release_views import build_plan  # noqa: E402
from verify_readonly_sql import verify  # noqa: E402


def _active_manifest() -> tuple[Path, dict[str, object]]:
    manifests = tuple(RELEASES.glob("*/manifest.json"))
    matches = []
    for path in manifests:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if document.get("expected", {}).get("serving_views"):
            matches.append((path, document))
    assert len(matches) == 1
    return matches[0]


def test_trino_recovery_plan_comes_from_manifest_metadata_and_ast() -> None:
    """실행 순서·필수 파일·13개 identity가 파일명 상수가 아닌 release에서 나온다."""

    manifest_path, manifest = _active_manifest()
    serving = str(manifest["namespaces"]["serving"])
    plan = build_plan(manifest_path, serving)
    entries = list(plan["files"])
    orders = [int(item["execution_order"]) for item in entries]
    required = [item for item in entries if item["mode"] == "required"]
    planned_views = {
        view
        for item in required
        for view in item["views"]
    }

    assert plan["release_id"] == manifest["release_id"]
    assert plan["view_count"] == manifest["expected"]["serving_views"]
    assert orders == sorted(orders)
    assert len(orders) == len(set(orders))
    assert planned_views == set(plan["views"])
    assert any(item["mode"] == "validation" for item in entries)
    assert any(item["mode"] == "preflight" for item in entries)


def test_all_manifest_source_validations_are_ast_verified_read_only() -> None:
    """각 source engine의 실제 validation SQL 전체가 조회 전용 AST로만 구성된다."""

    manifest_path, manifest = _active_manifest()
    dialect_by_segment = {
        "01_postgresql_pms": "postgres",
        "02_postgresql_banquet": "postgres",
        "03_mysql_pos": "mysql",
        "04_sqlserver_crm": "tsql",
        "05_clickhouse_facility": "clickhouse",
    }
    verified = []
    for receipt in manifest["files"]:
        relative = str(receipt["relative_path"])
        path = manifest_path.parent / relative
        if not path.name.startswith("50_") or not path.name.endswith("_validation.sql"):
            continue
        matching = [
            dialect
            for segment, dialect in dialect_by_segment.items()
            if segment in path.parts
        ]
        if not matching:
            continue
        assert len(matching) == 1
        assert verify(path, matching[0]) > 0
        verified.append(path)

    assert len(verified) == len(dialect_by_segment)
