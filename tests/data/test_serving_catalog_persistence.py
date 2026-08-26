"""영속 serving catalog의 release compiler와 기동 경계를 검증한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from sqlglot import parse


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "infrastructure" / "database"
SCRIPTS = DATABASE / "scripts"
sys.path.insert(0, str(SCRIPTS))

from initialize_serving_catalog import (  # noqa: E402
    _repository_env_path,
    main as initialize_main,
)
from render_release_serving_sql import ViewCoercion, load_coercions, render  # noqa: E402


def _voc_release_sql() -> Path:
    matches = tuple(DATABASE.glob("releases/*/01_V4.3_생성_및_서빙_SQL/06_trino_serving/26_trino_voc_views.sql"))
    assert len(matches) == 1
    return matches[0]


def test_iceberg_view_compiler_preserves_release_and_applies_contract() -> None:
    """불변 SQL은 건드리지 않고 namespace·무손실 type boundary만 AST 변환한다."""

    source = _voc_release_sql().read_text(encoding="utf-8-sig")
    contract = DATABASE / "trino" / "etc" / "iceberg-view-coercions.json"
    rendered = render(
        source,
        "serving.analytics_v4_3",
        "serving_next.analytics_v4_3",
        load_coercions(contract),
    )

    assert "CAST(r.submitted_at AS TIMESTAMP(6) WITH TIME ZONE) AS submitted_at" in rendered
    assert "CAST(r.rating_overall AS INTEGER) AS rating_overall" in rendered
    assert "CAST(r.language_code AS VARCHAR(2)) AS language_code" in rendered
    assert "serving.analytics_v4_3" not in rendered
    assert "CAST(r.submitted_at" not in source
    assert len(parse(rendered, read="trino")) == len(parse(source, read="trino"))


def test_iceberg_view_compiler_applies_coercions_without_namespace_change() -> None:
    """정식 serving cutover 뒤에도 connector type contract가 적용된다."""

    source = _voc_release_sql().read_text(encoding="utf-8-sig")
    contract = DATABASE / "trino" / "etc" / "iceberg-view-coercions.json"
    rendered = render(
        source,
        "serving.analytics_v4_3",
        "serving.analytics_v4_3",
        load_coercions(contract),
    )

    assert "CREATE OR REPLACE VIEW serving.analytics_v4_3.voc_review_detail" in rendered
    assert "CAST(r.submitted_at AS TIMESTAMP(6) WITH TIME ZONE) AS submitted_at" in rendered
    assert "CAST(r.prior_visit_count AS INTEGER) AS prior_visit_count" in rendered


def test_iceberg_view_coercion_contract_has_unique_auditable_rules() -> None:
    """각 coercion은 source/target type과 이유를 가진 고유 계약이어야 한다."""

    path = DATABASE / "trino" / "etc" / "iceberg-view-coercions.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    rules = document["coercions"]
    identities = {(rule["view"], rule["column"]) for rule in rules}

    assert len(identities) == len(rules)
    assert all(rule["source_type"] != rule["target_type"] for rule in rules)
    assert all(len(rule["reason"]) >= 40 for rule in rules)


def test_view_compiler_fails_closed_when_contract_column_is_missing() -> None:
    """오타 난 output identity를 조용히 무시하지 않는다."""

    rules = (
        ViewCoercion(
            view=("serving", "analytics_v4_3", "example_view"),
            column="missing_column",
            source_type="smallint",
            target_type="integer",
        ),
    )
    sql = "CREATE VIEW serving.analytics_v4_3.example_view AS SELECT 1 AS present_column"

    with pytest.raises(ValueError, match="must match exactly one SELECT output"):
        render(sql, "serving.analytics_v4_3", "serving_next.analytics_v4_3", rules)


def test_compose_uses_persistent_pinned_catalog_components() -> None:
    """catalog DB·object storage·token key와 Trino가 재시작 가능한 의존성을 가진다."""

    compose = (DATABASE / "compose.yml").read_text(encoding="utf-8")

    assert "apache/polaris:1.7.0@sha256:" in compose
    assert "rustfs/rustfs:1.0.0-beta.8@sha256:" in compose
    assert "trinodb/trino:483@sha256:" in compose
    assert "serving-catalog-postgres-data:/var/lib/postgresql/data" in compose
    assert "serving-object-store-data:/data" in compose
    assert "serving-catalog: { condition: service_healthy }" in compose

    serving = (DATABASE / "trino" / "etc" / "catalog" / "serving.properties").read_text(
        encoding="utf-8"
    )
    assert "connector.name=iceberg" in serving
    assert "iceberg.catalog.type=rest" in serving
    assert "connector.name=memory" not in serving
    assert not (
        DATABASE / "trino" / "etc" / "catalog" / "serving_next.properties"
    ).exists()


def test_core_start_initializes_scoped_catalog_identity_before_trino() -> None:
    """Core는 Polaris read-back과 scoped credential 결속 뒤에 전체 stack을 기동한다."""

    script = (SCRIPTS / "start.ps1").read_text(encoding="utf-8")
    initializer = script.index("initialize_serving_catalog.py")
    credential_gate = script.index("SERVING_CATALOG_TRINO_CLIENT_SECRET must contain")
    full_start = script.index("Invoke-Compose up --detach --wait --wait-timeout 1800 @coreStartupServices")

    assert initializer < credential_gate < full_start
    initializer_window = script[initializer:credential_gate]
    assert "--env-file" not in initializer_window
    assert "--allow-repository-local-development" not in initializer_window


def test_catalog_initializer_uses_only_fixed_gitignored_repository_env(tmp_path: Path) -> None:
    """initializer는 호출자가 고른 dotenv 대신 저장소의 고정 `.env`만 읽는다."""

    env_path = tmp_path / "infrastructure" / "database" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("SERVING_CATALOG_ADMIN_CLIENT_ID=test\n", encoding="utf-8")

    with patch(
        "initialize_serving_catalog.subprocess.run",
        return_value=CompletedProcess(args=[], returncode=0),
    ) as check_ignore:
        resolved = _repository_env_path(tmp_path)

    assert resolved == env_path.resolve()
    assert check_ignore.call_args.args[0][-1] == str(env_path)

    with patch(
        "initialize_serving_catalog.subprocess.run",
        return_value=CompletedProcess(args=[], returncode=1),
    ):
        with pytest.raises(ValueError, match="covered by .gitignore"):
            _repository_env_path(tmp_path)


def test_catalog_initializer_rejects_arbitrary_env_argument() -> None:
    """삭제된 env 인자를 조용히 무시해 외부 파일을 사용했다고 오해하게 하지 않는다."""

    with patch("sys.argv", ["initialize_serving_catalog.py", "--env-file", "outside.env"]):
        with pytest.raises(SystemExit) as error:
            initialize_main()

    assert error.value.code == 2
