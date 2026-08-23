"""Phase 6 sealed single-asset acceptance 경계와 Gold 무결성을 검증한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlglot import exp, parse_one


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "infrastructure" / "acceptance"
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(ACCEPTANCE), str(BACKEND), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from phase6_single_asset_analysis import (  # noqa: E402
    EXPECTED_ASSET_FQN,
    CAPABILITY_FILE,
    GOLD_FILE,
    Phase6Error,
    _ast_sha256,
    _gold,
    _validate_boundary,
    parse_args,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


def _args(extra: list[str] | None = None):
    values = [
        "--target-project",
        "answervice-phase2b-datahub",
        "--target-server",
        "https://127.0.0.1:38081",
        "--trino-server",
        "https://127.0.0.1:18443",
        "--trino-ca-file",
        str(Path(__file__).resolve()),
        "--database-url",
        "postgresql+psycopg://postgres@127.0.0.1:55440/phase4_runtime_catalog_acceptance",
    ]
    if extra:
        name, value = extra
        index = values.index(name)
        values[index + 1] = value
    return parse_args(values)


def test_gold_is_sealed_and_covers_every_single_asset_operation() -> None:
    document = _gold(GOLD_FILE)
    operations = {case["operation"] for case in document["cases"]}

    assert len(document["cases"]) == 8
    assert operations == {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    }
    assert any(len(case["metric_ids"]) > 1 for case in document["cases"])
    assert any(case["metric_ids"] == ["revpar"] for case in document["cases"])


def test_analysis_capability_is_sealed_to_one_catalog_and_asset() -> None:
    document = json.loads(CAPABILITY_FILE.read_text(encoding="utf-8"))
    payload = {
        key: value for key, value in document.items() if key != "content_sha256"
    }

    assert document["schema_version"] == "AnswerviceAnalysisCapabilityRelease.v1"
    assert document["status"] == "SEALED"
    assert document["content_sha256"] == canonical_sha256(payload)
    assert {item["fqn"] for item in document["contract"]["assets"]} == {
        EXPECTED_ASSET_FQN
    }
    assert "period_comparison" in document["contract"]["operations"]


def test_each_sealed_ast_and_oracle_stays_on_one_read_only_asset() -> None:
    document = _gold(GOLD_FILE)

    for case in document["cases"]:
        assert _ast_sha256(case["expected_canonical_sql"]) == case[
            "expected_ast_sha256"
        ]
        for field in ("expected_canonical_sql", "oracle_sql"):
            expression = parse_one(case[field], read="trino")
            assert isinstance(expression, exp.Select)
            assert not list(expression.find_all(exp.Join))
            assert {
                table.sql(dialect="trino").split(" AS ", 1)[0]
                for table in expression.find_all(exp.Table)
            } == {EXPECTED_ASSET_FQN}


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--target-project", "answervice", "target project"),
        ("--target-server", "https://127.0.0.1:18081", "target DataHub"),
        ("--trino-server", "https://127.0.0.1:28443", "source Trino"),
        (
            "--database-url",
            "postgresql+psycopg://postgres@127.0.0.1:5432/app_db",
            "database",
        ),
    ],
)
def test_boundary_rejects_current_or_unapproved_resources(
    option: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(Phase6Error, match=message):
        _validate_boundary(_args([option, value]))


def test_boundary_accepts_only_the_explicit_isolated_endpoints() -> None:
    _validate_boundary(_args())
