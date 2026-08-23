"""격리 환경에서 Phase 9 deterministic multi-asset JOIN Gate를 실행한다.

현재 Trino는 읽기 전용 분석·독립 기준 query 실행에만 사용한다. Metadata 발행은
``answervice-phase2b-datahub``에, projection·evidence·분석 실행 저장은 55440 격리 DB에만
한정한다. 세 JOIN 전략은 동일한 승인 edge에서 생성한 SQLGlot AST와 독립 Trino SQL 결과를
비교하고, 후보 활성화·rollback·재활성화를 CAS receipt로 남긴다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path
from time import time_ns
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url
from sqlglot import exp, parse_one


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.analysis_repository import PostgresAnalysisRepository  # noqa: E402
from app.adapters.catalog_snapshot import CatalogSnapshotLoader  # noqa: E402
from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.legacy_semantic_release import (  # noqa: E402
    compile_legacy_semantic_release,
)
from app.adapters.query_execution import QueryExecutionService  # noqa: E402
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    NATIVE_PRIORITY,
    RuntimeCatalogProjection,
    build_source_selection_manifest,
)
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ActiveRuntimeCatalogProjection,
    PostgresRuntimeCatalogProjectionRepository,
)
from app.adapters.trino_async import AdapterError, TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import TrinoSchemaInspector  # noqa: E402
from app.capability_contracts import (  # noqa: E402
    CatalogReceipt,
    ModelReceipt,
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
    ProductReleaseVector,
)
from app.contracts import AnalysisStatus  # noqa: E402
from app.database import get_sessionmaker  # noqa: E402
from app.query_capability import issue_query_capability  # noqa: E402
from app.services.analysis.logical_plan import (  # noqa: E402
    ANALYSIS_PLAN_VERSION,
    AnalysisPlanError,
    build_analysis_plan,
)
from app.services.analysis.typed_sql_compiler import (  # noqa: E402
    TYPED_SQL_COMPILER_VERSION,
)
from app.services.context.builder import (  # noqa: E402
    ContextBuildError,
    ContextPackageBuilder,
)
from app.services.context.runtime_contracts import time_selection_mode  # noqa: E402
from metadata_aspects import iter_aspects  # noqa: E402
from metadata_wire import validated_audit_stamp  # noqa: E402
from native_semantic_publication import (  # noqa: E402
    grouped_native_semantic_aspects,
    publish_native_semantic_shadow,
    verify_native_semantic_shadow,
)
from native_semantic_shadow import (  # noqa: E402
    NativeSemanticShadowError,
    native_semantic_shadow_projection,
)
from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    IsolatedSystemClient,
    TARGET_PORT,
    TARGET_PROJECT,
    _search_urns,
    _verify_with_freshness,
)
from phase3b_native_metric_shadow import RetryingIsolatedClient  # noqa: E402
from phase4_runtime_catalog_projection import (  # noqa: E402
    DATABASE_NAME,
    DATABASE_PORT,
    RuntimeSearchOnlyCatalog,
    StaticProjectionRepository,
    _native_records,
    _put_product_manifest,
    _readiness,
    _source_receipt,
)
from phase5_node1_grounding import (  # noqa: E402
    _active_manifest,
    _environment,
    _restore_previous,
)
from phase6_single_asset_analysis import (  # noqa: E402
    AcceptanceDataPlatform,
    ResultOnlyModel,
    _activation_receipts,
    _ast_sha256,
    _canonical_rows,
    _pipeline_run,
)
from phase9_join_authoring import (  # noqa: E402
    HOTEL_ASSET,
    PHASE9_JOIN_ID,
    VOC_ASSET,
    Phase9JoinAuthoringError,
    author_phase9_join_bundle,
)
from src.data.analysis_capability_contract import (  # noqa: E402
    ANALYSIS_CAPABILITY_VERSION,
    AnalysisCapabilityContract,
    compile_analysis_capability_contract,
)
from src.ai.model_contracts import (  # noqa: E402
    model_release_checksum,
    model_release_manifest,
)
from src.data.governance_contract import (  # noqa: E402
    canonical_sha256,
    catalog_hash,
)


ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
CAPABILITY_FILE = (
    ROOT / "app" / "backend" / "contracts"
    / "analysis_capability.multi_asset_join.v1.json"
)
GOLD_FILE = (
    ROOT / "evals" / "multi_asset_join_gold"
    / "answervice_ko_multi_asset_join.v1.json"
)
EXPECTED_PREVIOUS_PREFIX = "ANSWERVICE-PHASE8-NATIVE-SEMANTIC:"
PHASE9_PREFIX = "ANSWERVICE-PHASE9-MULTI-ASSET-JOIN:"
EXPECTED_CATALOG_SHA256 = (
    "695fe466056ee0e115eba39c985a1264f818faa960b8ba7d97da5f0f7ef4f2ed"
)
EXPECTED_CANONICAL_SHA256 = (
    "528870fc6a989ed14e3b9324c9e7ed72824357548812bc53ec9570ce08f35480"
)


class Phase9Error(AcceptanceError):
    """Phase 9 Gate를 낮추지 않고는 승인할 수 없음을 나타낸다."""


def _progress(stage: str, **details: object) -> None:
    """secret 없이 장시간 acceptance의 현재 단계를 stderr에 즉시 남긴다."""

    print(
        json.dumps(
            {"event": "phase9_progress", "stage": stage, **details},
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )


class Phase9ObservedDataPlatform:
    """실행 횟수와 terminal status shape만 남기고 query 값은 출력하지 않는다."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.execute_count = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
    ) -> dict[str, Any]:
        self.execute_count += 1
        try:
            result = await self._delegate.execute_query(
                sql,
                parameters,
                gate_token,
            )
        except Exception as error:
            _progress(
                "product_query_execute_failed",
                error_type=type(error).__name__,
            )
            raise
        _progress(
            "product_query_execute_returned",
            status=str(result.get("status") or ""),
            result_keys=sorted(map(str, result)),
        )
        return result

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        try:
            result = await self._delegate.get_query_status(query_id)
        except Exception as error:
            _progress(
                "product_query_status_failed",
                error_type=type(error).__name__,
            )
            raise
        _progress(
            "product_query_status_returned",
            status=str(result.get("status") or ""),
            result_keys=sorted(map(str, result)),
        )
        return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """승인된 격리 endpoint와 bounded timeout만 받는다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--target-server", required=True)
    parser.add_argument("--trino-server", required=True)
    parser.add_argument("--trino-ca-file", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--verify-timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def _validate_boundary(args: argparse.Namespace) -> None:
    if args.target_project != TARGET_PROJECT:
        raise Phase9Error("Phase 9 target project is outside the approved boundary")
    for endpoint, port, label in (
        (httpx.URL(args.target_server), TARGET_PORT, "target DataHub"),
        (httpx.URL(args.trino_server), 18443, "source Trino"),
    ):
        if (
            endpoint.scheme != "https"
            or endpoint.host not in {"127.0.0.1", "localhost", "::1"}
            or endpoint.port != port
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
        ):
            raise Phase9Error(f"{label} is outside the approved loopback boundary")
    database = make_url(args.database_url)
    if (
        database.drivername != "postgresql+psycopg"
        or database.host not in {"127.0.0.1", "localhost", "::1"}
        or database.port != DATABASE_PORT
        or database.database != DATABASE_NAME
        or database.username != "postgres"
        or database.password is not None
    ):
        raise Phase9Error("Phase 9 database is outside the isolated boundary")
    if args.timeout <= 0 or args.verify_timeout <= 0:
        raise Phase9Error("Phase 9 timeout must be positive")
    for supplied, expected, label in (
        (args.env_file, ENV_FILE, "environment"),
        (args.trino_ca_file, args.trino_ca_file, "Trino CA"),
    ):
        try:
            resolved = supplied.resolve(strict=True)
        except OSError as error:
            raise Phase9Error(f"Phase 9 {label} file is unavailable") from error
        if not resolved.is_file() or (
            label == "environment" and resolved != expected.resolve(strict=True)
        ):
            raise Phase9Error(f"Phase 9 {label} file differs from the sealed boundary")


def _sealed_json(path: Path, schema_version: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Phase9Error(f"sealed document is unreadable: {path.name}") from error
    if not isinstance(document, dict) or document.get("schema_version") != schema_version:
        raise Phase9Error(f"sealed document schema differs: {path.name}")
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    if (
        document.get("status") != "SEALED"
        or document.get("content_sha256") != canonical_sha256(payload)
    ):
        raise Phase9Error(f"sealed document checksum differs: {path.name}")
    return document


def _gold() -> dict[str, Any]:
    document = _sealed_json(GOLD_FILE, "answervice.multi_asset_join_gold.v1")
    cases = document.get("cases")
    negatives = document.get("negative_cases")
    if (
        not isinstance(cases, list)
        or len(cases) != 3
        or {str(item.get("expected_strategy")) for item in cases}
        != {"DIRECT_JOIN", "PREAGGREGATE", "SEMI_JOIN"}
        or not isinstance(negatives, list)
        or {str(item.get("kind")) for item in negatives}
        != {"many_to_many", "ambiguous_shortest_path", "mixed_time_mode"}
    ):
        raise Phase9Error("Phase 9 Gold strategy or negative coverage differs")
    return document


def _capability(
    active: ActiveRuntimeCatalogProjection,
) -> tuple[dict[str, Any], AnalysisCapabilityContract]:
    document = _sealed_json(
        CAPABILITY_FILE, "AnswerviceAnalysisCapabilityRelease.v1"
    )
    projection = active.projection
    if (
        document.get("catalog_release_id") != projection.catalog_release_id
        or document.get("catalog_sha256") != projection.catalog_sha256
        or document.get("canonical_sha256") != projection.canonical_sha256
    ):
        raise Phase9Error("Phase 9 capability release receipt differs")
    datasets = projection.snapshot.datasets_by_fqn
    dimension_columns: dict[str, set[str]] = {}
    for dataset in datasets.values():
        for dimension in dataset.dimensions:
            if (
                isinstance(dimension, Mapping)
                and isinstance(dimension.get("id"), str)
                and isinstance(dimension.get("column"), str)
            ):
                dimension_columns.setdefault(str(dimension["id"]), set()).add(
                    str(dimension["column"])
                )
    try:
        contract = compile_analysis_capability_contract(
            document["contract"],
            available_fields_by_asset={
                fqn: frozenset(str(column["name"]) for column in dataset.columns)
                for fqn, dataset in datasets.items()
            },
            dimension_family_columns={
                name: frozenset(columns)
                for name, columns in dimension_columns.items()
            },
        )
    except ValueError as error:
        raise Phase9Error("Phase 9 capability is not catalog-bound") from error
    if (
        contract.version != ANALYSIS_CAPABILITY_VERSION
        or set(contract.operations) != {"aggregate", "breakdown"}
        or contract.max_metrics_per_plan != 2
        or {item.asset_fqn for item in contract.assets} != {HOTEL_ASSET, VOC_ASSET}
    ):
        raise Phase9Error("Phase 9 capability matrix differs")
    return document, contract


def _manifest(
    projection: RuntimeCatalogProjection,
    previous: ProductReleaseEvidenceManifest,
    gold: Mapping[str, Any],
    capability: Mapping[str, Any],
    native_projection: Mapping[str, Any],
) -> ProductReleaseEvidenceManifest:
    """후보 catalog·compiler·Gold·native relationship을 하나의 제품 receipt로 봉인한다."""

    source, created_at = _source_receipt()
    model_manifest = model_release_manifest()
    evidence = ProductReleaseEvidence(
        source=source,
        images=previous.evidence.images,
        migration=previous.evidence.migration,
        model=ModelReceipt(
            release_id=str(model_manifest["manifest_version"]),
            manifest_sha256=model_release_checksum(),
        ),
        catalog=CatalogReceipt(
            release_id=projection.catalog_release_id,
            manifest_sha256=projection.manifest_sha256,
            projection_sha256=projection.projection_sha256,
        ),
        release_vector=ProductReleaseVector(
            data_release_id=projection.catalog_release_id,
            semantic_release_id=projection.catalog_release_id,
            prompt_release_id=str(model_manifest["manifest_version"]),
            policy_release_id=projection.release.policy_version,
            runtime_release_id="PHASE9-RUNTIME-v1:"
            + canonical_sha256(
                {
                    "analysis_plan": ANALYSIS_PLAN_VERSION,
                    "compiler": TYPED_SQL_COMPILER_VERSION,
                    "capability_sha256": capability["content_sha256"],
                    "gold_sha256": gold["content_sha256"],
                    "native_projection_sha256": native_projection["projection_sha256"],
                }
            ),
        ),
    )
    identity = canonical_sha256(
        {
            "phase": "9",
            "contract": "deterministic_multi_asset_join.v1",
            "join_id": PHASE9_JOIN_ID,
            "evidence": evidence.model_dump(mode="json"),
            "capability_sha256": capability["content_sha256"],
            "gold_sha256": gold["content_sha256"],
            "native_projection_sha256": native_projection["projection_sha256"],
        }
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=f"{PHASE9_PREFIX}{identity}",
        evidence=evidence,
        created_at=created_at,
    )


async def _publish_legacy_bundle(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    actor_urn: str,
    verify_timeout: float,
) -> int:
    """기존 entity membership 안에서 versioned legacy aspect를 exact upsert한다."""

    audit = validated_audit_stamp(
        {"actor": actor_urn, "time": time_ns() // 1_000_000}
    )
    grouped: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for entity_type, urn, name, value in iter_aspects(bundle):
        grouped.setdefault((entity_type, urn), {})[name] = value
    for (entity_type, urn), aspects in sorted(grouped.items()):
        await client.upsert_entity(entity_type, urn, aspects, audit)
    await _verify_with_freshness(
        client, bundle, timeout_seconds=verify_timeout
    )
    return len(grouped)


async def _target_scope_with_native(
    client: Any,
    bundle: Mapping[str, Any],
) -> dict[str, int]:
    """legacy release와 Phase 8 native semantic mirror의 exact membership만 허용한다."""

    legacy_datasets = {
        str(asset["urn"]) for asset in bundle["schema_context"]["assets"]
    }
    native_datasets = {
        urn
        for (entity_type, urn) in grouped_native_semantic_aspects(bundle)
        if entity_type == "dataset"
    }
    expected_terms = {str(term["urn"]) for term in bundle["metric_terms"]}
    datasets = await _search_urns(client, "DATASET")
    terms = await _search_urns(client, "GLOSSARY_TERM")
    if datasets != legacy_datasets | native_datasets or terms != expected_terms:
        raise Phase9Error("isolated target legacy/native membership differs")
    return {
        "legacy_dataset_count": len(legacy_datasets),
        "native_semantic_dataset_count": len(native_datasets),
        "glossary_term_count": len(expected_terms),
    }


def _physical_tables(sql: str) -> set[str]:
    expression = parse_one(sql, read="trino")
    return {
        table.sql(dialect="trino").split(" AS ", 1)[0]
        for table in expression.find_all(exp.Table)
    }


def _validate_model_call_gate(calls: list[str], expected_node3_calls: int) -> None:
    """Node 1/2는 0건, 단일 Metric 결과 설명용 Node 3만 정확히 허용한다."""

    if (
        any(node != "node3" for node in calls)
        or calls.count("node3") != expected_node3_calls
    ):
        raise Phase9Error(
            "Phase 9 model call boundary differs from deterministic compiler contract"
        )


async def _evaluate_case(
    *,
    case: Mapping[str, Any],
    ordinal: int,
    platform: Phase9ObservedDataPlatform,
    model: ResultOnlyModel,
    repository: PostgresAnalysisRepository,
    owner_id: Any,
    manifest: ProductReleaseEvidenceManifest,
    candidate: ActiveRuntimeCatalogProjection,
    oracle_execution: QueryExecutionService,
) -> tuple[dict[str, Any], Any]:
    """typed pipeline 결과를 독립 기준 SQL 결과와 exact 비교한다."""

    before = platform.execute_count
    response, execution, context = await _pipeline_run(
        platform=platform,
        model=model,
        repository=repository,
        owner_id=owner_id,
        manifest=manifest,
        semantic_release_id=candidate.projection.catalog_release_id,
        case=case,
        as_of=date.fromisoformat(str(case.get("as_of") or "2025-09-02")),
        trace_prefix=f"phase9-{ordinal}-{uuid4().hex[:10]}",
    )
    if (
        response.data.status is not AnalysisStatus.SUCCEEDED
        or response.data.artifact is None
        or response.data.result is None
        or platform.execute_count != before + 1
        or set(execution) != {"plan", "query", "package"}
    ):
        error_code = response.error.code.value if response.error is not None else None
        raise Phase9Error(
            f"Phase 9 case failed before oracle comparison: {case['case_id']}; "
            f"status={response.data.status.value}; error_code={error_code}"
        )
    plan = execution["plan"]
    logical = plan.get("analysis_plan")
    ast_evidence = plan.get("ast_evidence")
    strategy = str(case["expected_strategy"])
    expected_join_count = 0 if strategy == "SEMI_JOIN" else 1
    logical_joins = logical.get("joins") if isinstance(logical, Mapping) else None
    if (
        plan.get("plan_source") != "typed_sql_compiler"
        or plan.get("model_version") != TYPED_SQL_COMPILER_VERSION
        or not isinstance(logical, Mapping)
        or logical.get("version") != ANALYSIS_PLAN_VERSION
        or not isinstance(logical_joins, list)
        or len(logical_joins) != 1
        or not isinstance(logical_joins[0], Mapping)
        or set(logical_joins[0]) != {"join_id", "plan", "reason"}
        or logical_joins[0].get("join_id") != PHASE9_JOIN_ID
        or logical_joins[0].get("plan") != strategy
        or not isinstance(ast_evidence, Mapping)
        or ast_evidence.get("projection_aliases") != case["expected_columns"]
        or ast_evidence.get("join_count") != expected_join_count
        or set(ast_evidence.get("physical_tables", ())) != {HOTEL_ASSET, VOC_ASSET}
        or len(ast_evidence.get("fanout_plans", ())) != 1
        or ast_evidence["fanout_plans"][0].get("join_id") != PHASE9_JOIN_ID
        or ast_evidence["fanout_plans"][0].get("plan") != strategy
        or _physical_tables(str(plan.get("sql") or "")) != {HOTEL_ASSET, VOC_ASSET}
    ):
        raise Phase9Error(f"Phase 9 governed AST differs: {case['case_id']}")
    try:
        oracle_sql = str(case["oracle_sql"])
        oracle_result = await oracle_execution.execute(
            oracle_sql,
            {},
            issue_query_capability("0" * 64, oracle_sql),
        )
    except (ConnectionError, TimeoutError, ValueError) as error:
        raise Phase9Error(
            "Phase 9 independent reference query failed: "
            f"{case['case_id']}; error_type={type(error).__name__}"
        ) from error
    oracle_metadata = oracle_result.get("result_metadata")
    oracle_columns = (
        tuple(str(item.get("name") or "") for item in oracle_metadata["columns"])
        if isinstance(oracle_metadata, Mapping)
        and isinstance(oracle_metadata.get("columns"), list)
        and all(isinstance(item, Mapping) for item in oracle_metadata["columns"])
        else ()
    )
    oracle_rows = [dict(row) for row in oracle_result.get("rows", ())]
    pipeline_rows = [dict(row) for row in execution["query"].get("rows", ())]
    if (
        oracle_result.get("status") != "SUCCEEDED"
        or oracle_columns != tuple(case["expected_columns"])
        or _canonical_rows(pipeline_rows) != _canonical_rows(oracle_rows)
    ):
        raise Phase9Error(
            f"Phase 9 duplicate aggregation reference differs: {case['case_id']}"
        )
    evidence = response.data.result.evidence
    if (
        evidence.product_release_id != manifest.product_release_id
        or evidence.context_release != candidate.projection.catalog_release_id
        or evidence.query_id != response.data.artifact.query_id
        or response.data.artifact.context_hash != execution["package"].package_hash
    ):
        raise Phase9Error(f"Phase 9 result receipt differs: {case['case_id']}")
    return (
        {
            "case_id": case["case_id"],
            "exact": True,
            "strategy": strategy,
            "row_count": len(pipeline_rows),
            "ast_sha256": _ast_sha256(str(plan["sql"])),
            "result_sha256": hashlib.sha256(
                _canonical_rows(pipeline_rows).encode()
            ).hexdigest(),
            "fanout_reason": ast_evidence["fanout_plans"][0]["reason"],
        },
        execution["package"],
    )


def _negative_gates(
    package: Any,
    direct_case: Mapping[str, Any],
    negative_cases: list[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """many-to-many·경로 모호성·혼합 time mode를 typed failure로 고정한다."""

    edge = package.join_graph[0]
    structured = {
        "selected_metric_id": str(direct_case["metric_ids"][0]),
        "analysis_operation": str(direct_case["operation"]),
        "period_relationship": "single",
        "dimension_fields": [
            {"asset_fqn": HOTEL_ASSET, "column": "hotel_code"}
        ],
    }
    expected = {str(item["kind"]): str(item["expected_error"]) for item in negative_cases}
    results: list[dict[str, str]] = []

    try:
        build_analysis_plan(
            structured,
            replace(package, join_graph=(replace(edge, cardinality="many_to_many"),)),
        )
    except AnalysisPlanError as error:
        actual = error.code.value
    else:  # pragma: no cover - Gate invariant
        raise Phase9Error("many-to-many plan was accepted")
    if actual != expected["many_to_many"]:
        raise Phase9Error("many-to-many failure code differs")
    results.append({"kind": "many_to_many", "error": actual})

    duplicate = replace(edge, id=f"{edge.id}_duplicate")
    allowed = (str(edge.id), str(duplicate.id))
    ambiguous_metrics = tuple(
        replace(metric, allowed_join_ids=allowed) for metric in package.metrics
    )
    try:
        build_analysis_plan(
            structured,
            replace(
                package,
                metrics=ambiguous_metrics,
                join_graph=(edge, duplicate),
            ),
        )
    except AnalysisPlanError as error:
        actual = error.code.value
    else:  # pragma: no cover - Gate invariant
        raise Phase9Error("ambiguous shortest path was accepted")
    if actual != expected["ambiguous_shortest_path"]:
        raise Phase9Error("ambiguous shortest path failure code differs")
    results.append({"kind": "ambiguous_shortest_path", "error": actual})

    range_metadata = {
        "mode": "range",
        "calendar_id": "gregorian-kr",
        "start_parameter": "start_date",
        "end_parameter": "end_date",
        "fields": [],
    }
    snapshot_metadata = {
        "mode": "latest_snapshot",
        "calendar_id": "gregorian-kr",
        "selection": "max_source_value_lt_as_of",
        "as_of_parameter": "as_of_date",
        "fields": [],
    }
    try:
        time_selection_mode(
            [
                {"time_metadata": range_metadata},
                {"time_metadata": snapshot_metadata},
            ]
        )
    except ContextBuildError as error:
        actual = error.code.value
    else:  # pragma: no cover - Gate invariant
        raise Phase9Error("mixed time mode was accepted")
    if actual != expected["mixed_time_mode"]:
        raise Phase9Error("mixed time mode failure code differs")
    results.append({"kind": "mixed_time_mode", "error": actual})
    return results


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """후보 발행, 세 전략 실행, negative, activation·rollback을 순서대로 검증한다."""

    _validate_boundary(args)
    environment = _environment(args.env_file)
    gold = _gold()
    sessionmaker = get_sessionmaker(args.database_url)
    projection_repository = PostgresRuntimeCatalogProjectionRepository(sessionmaker)
    previous_active = await projection_repository.load_active()
    if (
        previous_active.generation < 18
        or not previous_active.product_release_id.startswith(EXPECTED_PREVIOUS_PREFIX)
        or previous_active.projection.source_selection.get("authority_mode")
        != NATIVE_PRIORITY
    ):
        raise Phase9Error("Phase 9 requires the verified Phase 8 active pointer")
    previous_bundle = previous_active.projection.release.as_bundle()
    candidate_bundle = author_phase9_join_bundle(previous_bundle)
    if (
        catalog_hash(candidate_bundle) != EXPECTED_CATALOG_SHA256
        or candidate_bundle["join_graph"]["edges"][0]["id"] != PHASE9_JOIN_ID
    ):
        raise Phase9Error("Phase 9 authored bundle identity differs")
    native_projection = native_semantic_shadow_projection(candidate_bundle)
    if native_projection.get("relationship_count") != 1:
        raise Phase9Error("Phase 9 native relationship inventory differs")
    previous_manifest = await _active_manifest(
        sessionmaker, previous_active.product_release_id
    )

    ca_file = Path(environment["PHASE5_DATAHUB_CA_FILE"]).resolve(strict=True)
    account = token_id = None
    catalog: DataHubCatalogClient | None = None
    trino: TrinoAsyncClient | None = None
    oracle_trino: TrinoAsyncClient | None = None
    engines: list[QueryGovernanceEngine] = []
    metadata_state = "previous"
    activated = False
    gate_complete = False
    cleanup_errors: list[BaseException] = []
    try:
        async with IsolatedSystemClient(
            args.target_server,
            ca_file=ca_file,
            client_id=environment["DATAHUB_SYSTEM_CLIENT_ID"],
            client_secret=environment["DATAHUB_SYSTEM_CLIENT_SECRET"],
            timeout_seconds=args.timeout,
        ) as raw_system:
            system = RetryingIsolatedClient(raw_system)
            actor_urn = f"urn:li:corpuser:{environment['DATAHUB_SYSTEM_CLIENT_ID']}"
            target_scope = await _target_scope_with_native(
                raw_system, previous_bundle
            )
            try:
                metadata_state = "candidate_attempted"
                published_legacy_count = await _publish_legacy_bundle(
                    system,
                    candidate_bundle,
                    actor_urn=actor_urn,
                    verify_timeout=args.verify_timeout,
                )
                await publish_native_semantic_shadow(
                    system,
                    candidate_bundle,
                    actor_urn=actor_urn,
                    expected_projection_sha256=native_projection["projection_sha256"],
                )
                native_verified = await verify_native_semantic_shadow(
                    system,
                    candidate_bundle,
                    expected_projection_sha256=native_projection["projection_sha256"],
                )
                metadata_state = "candidate"
                _progress("candidate_metadata_verified")

                account = await raw_system.create_temporary_service_account()
                token, token_id = await raw_system.create_temporary_access_token(account)
                catalog = DataHubCatalogClient(
                    args.target_server,
                    token,
                    ca_file=ca_file,
                    expected_actor_urn=account,
                    timeout_seconds=args.timeout,
                    page_size=50,
                    max_entities=10_000,
                )
                try:
                    healthy = await catalog.health()
                except DataHubCatalogError as error:
                    raise Phase9Error(
                        f"target DataHub read identity failed: {error.category}"
                    ) from error
                if not healthy:
                    raise Phase9Error("temporary target DataHub identity is unhealthy")
                snapshot = await CatalogSnapshotLoader(
                    catalog,
                    max_concurrency=3,
                    ttl_seconds=max(args.verify_timeout, 1.0),
                ).load()
                release = compile_legacy_semantic_release(
                    snapshot, str(candidate_bundle["catalog_version"])
                )
                if (
                    release.catalog_checksum != EXPECTED_CATALOG_SHA256
                    or release.canonical_checksum != EXPECTED_CANONICAL_SHA256
                ):
                    raise Phase9Error("Phase 9 target full read-back differs")
                _progress("candidate_snapshot_compiled")

                trino = TrinoAsyncClient(
                    args.trino_server,
                    environment["TRINO_DATAHUB_USER"],
                    environment["TRINO_DATAHUB_PASSWORD"],
                    ca_file=args.trino_ca_file,
                    request_timeout_seconds=args.timeout,
                )
                oracle_trino = TrinoAsyncClient(
                    args.trino_server,
                    environment["TRINO_DATAHUB_USER"],
                    environment["TRINO_DATAHUB_PASSWORD"],
                    ca_file=args.trino_ca_file,
                    request_timeout_seconds=args.timeout,
                )
                schema = TrinoSchemaInspector(trino, timeout_seconds=args.timeout)
                previous_assets = {
                    item.fqn: (
                        previous_active.projection.snapshot.datasets_by_fqn[
                            item.fqn
                        ].table_type,
                        previous_active.projection.snapshot.datasets_by_fqn[
                            item.fqn
                        ].trino_schema_checksum,
                        len(
                            previous_active.projection.snapshot.datasets_by_fqn[
                                item.fqn
                            ].trino_schema_columns
                        ),
                    )
                    for item in previous_active.projection.release.assets
                }
                candidate_assets = {
                    item.fqn: (
                        snapshot.datasets_by_fqn[item.fqn].table_type,
                        snapshot.datasets_by_fqn[item.fqn].trino_schema_checksum,
                        len(snapshot.datasets_by_fqn[item.fqn].trino_schema_columns),
                    )
                    for item in release.assets
                }
                if previous_assets != candidate_assets:
                    raise Phase9Error(
                        "Phase 9 candidate changed the sealed physical schema surface"
                    )
                sealed_fingerprints = {
                    str(item["fqn"]): dict(item)
                    for item in previous_active.projection.trino_fingerprints
                }
                live_join_fingerprints = await schema.fingerprints(
                    tuple(
                        snapshot.datasets_by_fqn[fqn]
                        for fqn in (HOTEL_ASSET, VOC_ASSET)
                    )
                )
                if any(
                    dict(item) != sealed_fingerprints.get(str(item["fqn"]))
                    for item in live_join_fingerprints
                ):
                    raise Phase9Error(
                        "Phase 9 joined asset live Trino fingerprint differs"
                    )
                _progress("joined_schema_verified")
                fingerprints = previous_active.projection.trino_fingerprints
                projection = RuntimeCatalogProjection.compile(
                    snapshot,
                    release,
                    source_selection=build_source_selection_manifest(
                        release,
                        authority_mode=NATIVE_PRIORITY,
                        native_records=_native_records(candidate_bundle),
                        native_projection_sha256=native_projection["projection_sha256"],
                        native_membership_sha256=native_projection[
                            "release_membership_sha256"
                        ],
                    ),
                    trino_fingerprints=fingerprints,
                )
                # Out-of-band schema probe와 runtime query가 같은 HTTP pool의
                # connection lifecycle을 공유하지 않게 경계를 분리한다.
                await trino.aclose()
                trino = TrinoAsyncClient(
                    args.trino_server,
                    environment["TRINO_DATAHUB_USER"],
                    environment["TRINO_DATAHUB_PASSWORD"],
                    ca_file=args.trino_ca_file,
                    request_timeout_seconds=args.timeout,
                )
                schema = TrinoSchemaInspector(trino, timeout_seconds=args.timeout)
                await projection_repository.put_projection(projection)
                candidate_stub = ActiveRuntimeCatalogProjection(
                    generation=previous_active.generation,
                    product_release_id="candidate-unbound",
                    projection=projection,
                )
                capability_document, capability = _capability(candidate_stub)
                manifest = _manifest(
                    projection,
                    previous_manifest,
                    gold,
                    capability_document,
                    native_projection,
                )
                await _put_product_manifest(sessionmaker, manifest)
                candidate = await projection_repository.load_candidate(
                    projection.projection_id, manifest.product_release_id
                )

                runtime_catalog = RuntimeSearchOnlyCatalog(catalog)
                candidate_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    schema,
                    expected_context_release=projection.catalog_release_id,
                    search_mode="datahub_lexical",
                    projection_repository=StaticProjectionRepository(candidate),
                    analysis_capability=capability,
                )
                engines.append(candidate_engine)
                readiness, readiness_receipt, readiness_latency = await _readiness(
                    candidate_engine
                )
                if readiness_receipt != manifest.product_release_id:
                    raise Phase9Error("Phase 9 candidate readiness receipt differs")
                platform = Phase9ObservedDataPlatform(
                    AcceptanceDataPlatform(
                        candidate_engine,
                        QueryExecutionService(
                            trino,
                            timeout_seconds=args.timeout,
                            state_ttl_seconds=300,
                            state_max_entries=20,
                        ),
                        catalog,
                        trino,
                    )
                )
                model = ResultOnlyModel()
                oracle_execution = QueryExecutionService(
                    oracle_trino,
                    timeout_seconds=args.timeout,
                    state_ttl_seconds=300,
                    state_max_entries=20,
                )
                owner_id = uuid4()
                analysis_repository = PostgresAnalysisRepository(
                    args.database_url,
                    owner_id,
                    session_factory=sessionmaker,
                )
                case_results: list[dict[str, Any]] = []
                direct_package = None
                expected_node3_calls = 0
                for ordinal, case in enumerate(gold["cases"], start=900):
                    _progress(
                        "case_started",
                        case_id=str(case["case_id"]),
                        strategy=str(case["expected_strategy"]),
                    )
                    result, package = await _evaluate_case(
                        case={**case, "as_of": gold["as_of"]},
                        ordinal=ordinal,
                        platform=platform,
                        model=model,
                        repository=analysis_repository,
                        owner_id=owner_id,
                        manifest=manifest,
                        candidate=candidate,
                        oracle_execution=oracle_execution,
                    )
                    case_results.append(result)
                    if len(package.metric_terms) == 1:
                        expected_node3_calls += 1
                    _progress(
                        "case_passed",
                        case_id=str(case["case_id"]),
                        strategy=str(case["expected_strategy"]),
                    )
                    if case["expected_strategy"] == "DIRECT_JOIN":
                        direct_package = package
                if direct_package is None:
                    raise Phase9Error("Phase 9 DIRECT_JOIN package evidence is missing")
                _validate_model_call_gate(model.calls, expected_node3_calls)
                negative_results = _negative_gates(
                    direct_package,
                    gold["cases"][0],
                    gold["negative_cases"],
                )
                _progress("negative_cases_passed")

                activated_pointer = await projection_repository.activate(
                    projection_id=projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=previous_active.generation,
                    action="ACTIVATE",
                    actor="phase9-acceptance",
                    reason="three deterministic JOIN strategies and Trino Gold passed",
                )
                activated = True
                rolled_back = await projection_repository.activate(
                    projection_id=previous_active.projection.projection_id,
                    product_release_id=previous_active.product_release_id,
                    expected_generation=activated_pointer.generation,
                    action="ROLLBACK",
                    actor="phase9-acceptance",
                    reason="rehearse exact Phase 9 product rollback",
                )
                activated = False
                metadata_state = "previous_attempted"
                await _publish_legacy_bundle(
                    system,
                    previous_bundle,
                    actor_urn=actor_urn,
                    verify_timeout=args.verify_timeout,
                )
                await publish_native_semantic_shadow(
                    system,
                    previous_bundle,
                    actor_urn=actor_urn,
                    expected_projection_sha256=native_semantic_shadow_projection(
                        previous_bundle
                    )["projection_sha256"],
                )
                await verify_native_semantic_shadow(
                    system,
                    previous_bundle,
                    expected_projection_sha256=native_semantic_shadow_projection(
                        previous_bundle
                    )["projection_sha256"],
                )
                metadata_state = "previous"

                metadata_state = "candidate_attempted"
                await _publish_legacy_bundle(
                    system,
                    candidate_bundle,
                    actor_urn=actor_urn,
                    verify_timeout=args.verify_timeout,
                )
                await publish_native_semantic_shadow(
                    system,
                    candidate_bundle,
                    actor_urn=actor_urn,
                    expected_projection_sha256=native_projection["projection_sha256"],
                )
                await verify_native_semantic_shadow(
                    system,
                    candidate_bundle,
                    expected_projection_sha256=native_projection["projection_sha256"],
                )
                metadata_state = "candidate"
                final_active = await projection_repository.activate(
                    projection_id=projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=rolled_back.generation,
                    action="ACTIVATE",
                    actor="phase9-acceptance",
                    reason="reactivate verified Phase 9 multi-asset release",
                )
                activated = True
                active_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    schema,
                    expected_context_release=projection.catalog_release_id,
                    search_mode="datahub_lexical",
                    projection_repository=projection_repository,
                    analysis_capability=capability,
                )
                engines.append(active_engine)
                active_stages, active_receipt, active_latency = await _readiness(
                    active_engine
                )
                if active_receipt != manifest.product_release_id:
                    raise Phase9Error("Phase 9 final active readiness differs")
                receipts = await _activation_receipts(
                    sessionmaker, manifest.product_release_id
                )
                tail = receipts[-3:]
                if [item["action"] for item in tail] != [
                    "ACTIVATE",
                    "ROLLBACK",
                    "ACTIVATE",
                ]:
                    raise Phase9Error("Phase 9 activation receipt sequence differs")
                verified_active = await projection_repository.load_active()
                if (
                    verified_active.product_release_id != manifest.product_release_id
                    or verified_active.generation != final_active.generation
                ):
                    raise Phase9Error("Phase 9 final active pointer differs")
                _progress(
                    "activation_rehearsal_passed",
                    generation=verified_active.generation,
                )
                gate_complete = True
                return {
                    "status": "PHASE9_MULTI_ASSET_JOIN_PASSED",
                    "target_project": args.target_project,
                    "database": DATABASE_NAME,
                    "previous_product_release_id": previous_active.product_release_id,
                    "product_release_id": manifest.product_release_id,
                    "final_generation": verified_active.generation,
                    "catalog_release_id": projection.catalog_release_id,
                    "catalog_sha256": projection.catalog_sha256,
                    "canonical_sha256": projection.canonical_sha256,
                    "projection_sha256": projection.projection_sha256,
                    "native_relationship_count": native_projection["relationship_count"],
                    "target_scope": target_scope,
                    "native_readback_projection_sha256": native_verified[
                        "readback_projection_sha256"
                    ],
                    "published_legacy_entity_count": published_legacy_count,
                    "trino_fingerprint_reuse": {
                        "sealed_asset_count": len(fingerprints),
                        "live_join_asset_count": len(live_join_fingerprints),
                        "physical_surface_equal": True,
                        "runtime_client_reopened": True,
                        "independent_oracle_client": True,
                    },
                    "case_results": case_results,
                    "strategy_coverage": sorted(
                        item["strategy"] for item in case_results
                    ),
                    "negative_results": negative_results,
                    "duplicate_aggregation_count": 0,
                    "unapproved_edge_count": 0,
                    "node1_call_count": 0,
                    "node2_call_count": 0,
                    "node3_call_count": expected_node3_calls,
                    "sql_execution_count": platform.execute_count,
                    "candidate_readiness": {
                        "stages": readiness,
                        "latency_ms": readiness_latency,
                    },
                    "active_readiness": {
                        "stages": active_stages,
                        "latency_ms": active_latency,
                    },
                    "activation_receipts": tail,
                    "runtime_full_scroll_attempt_count": (
                        runtime_catalog.full_read_attempt_count
                    ),
                    "temporary_read_token_revoked": True,
                    "temporary_service_account_deleted": True,
                }
            except BaseException:
                if activated and not gate_complete:
                    try:
                        await _restore_previous(
                            projection_repository, previous_active
                        )
                        activated = False
                    except BaseException as error:
                        cleanup_errors.append(error)
                if metadata_state != "previous" and not gate_complete:
                    try:
                        await _publish_legacy_bundle(
                            system,
                            previous_bundle,
                            actor_urn=actor_urn,
                            verify_timeout=args.verify_timeout,
                        )
                        previous_native = native_semantic_shadow_projection(
                            previous_bundle
                        )
                        await publish_native_semantic_shadow(
                            system,
                            previous_bundle,
                            actor_urn=actor_urn,
                            expected_projection_sha256=previous_native[
                                "projection_sha256"
                            ],
                        )
                        await verify_native_semantic_shadow(
                            system,
                            previous_bundle,
                            expected_projection_sha256=previous_native[
                                "projection_sha256"
                            ],
                        )
                        metadata_state = "previous"
                    except BaseException as error:
                        cleanup_errors.append(error)
                raise
            finally:
                for engine in reversed(engines):
                    try:
                        await engine.aclose()
                    except BaseException as error:
                        cleanup_errors.append(error)
                if catalog is not None:
                    try:
                        await catalog.aclose()
                    except BaseException as error:
                        cleanup_errors.append(error)
                if trino is not None:
                    try:
                        await trino.aclose()
                    except BaseException as error:
                        cleanup_errors.append(error)
                if oracle_trino is not None:
                    try:
                        await oracle_trino.aclose()
                    except BaseException as error:
                        cleanup_errors.append(error)
                if token_id is not None:
                    try:
                        await raw_system.revoke_access_token(token_id)
                    except BaseException as error:
                        cleanup_errors.append(error)
                if account is not None:
                    try:
                        await raw_system.delete_service_account(account)
                    except BaseException as error:
                        cleanup_errors.append(error)
    finally:
        if cleanup_errors:
            raise Phase9Error("Phase 9 temporary resource cleanup failed") from cleanup_errors[0]


def _run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(run(args))
    return asyncio.run(run(args))


def main(argv: list[str] | None = None) -> int:
    """secret 없는 성공 또는 typed 실패 JSON을 출력한다."""

    try:
        result = _run_acceptance(parse_args(argv))
    except (
        AcceptanceError,
        AdapterError,
        NativeSemanticShadowError,
        Phase9JoinAuthoringError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        output = {"status": "FAILED", "error_type": type(error).__name__}
        if isinstance(
            error,
            (
                AcceptanceError,
                NativeSemanticShadowError,
                Phase9JoinAuthoringError,
            ),
        ):
            output["reason"] = str(error)
        print(json.dumps(output, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
