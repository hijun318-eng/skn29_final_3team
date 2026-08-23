"""Run the Phase 6 same-asset analysis Gate against the isolated stack.

The runner uses a sealed SQL AST/result oracle, the active immutable runtime
projection, the source Trino in read-only mode, and only the isolated Phase 4
acceptance database.  Node 1 is already sealed by Phase 5, so every positive
case enters through typed ``ResolvedSlots`` and proves that Node 2 is never
called for the deterministic single-serving-view capability.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import httpx
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import exp, parse_one


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.analysis_repository import PostgresAnalysisRepository  # noqa: E402
from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.query_execution import QueryExecutionService  # noqa: E402
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ActiveRuntimeCatalogProjection,
    PostgresRuntimeCatalogProjectionRepository,
    RuntimeCatalogRepositoryError,
)
from app.adapters.trino_async import AdapterError, QueryPage, TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import (  # noqa: E402
    TrinoSchemaDriftError,
    TrinoSchemaInspector,
)
from app.capability_contracts import (  # noqa: E402
    CatalogReceipt,
    MigrationReceipt,
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
    ProductReleaseVector,
)
from app.contracts import (  # noqa: E402
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    ErrorCode,
    RequestContext,
    ResolvedSlots,
    Role,
    RouteType,
)
from app.database import get_sessionmaker  # noqa: E402
from app.ports.data_platform import (  # noqa: E402
    AssetCandidateSet,
    ExecutionAssetSelection,
    ReleaseReceiptChangedError,
)
from app.services.analysis.service import AnalysisService  # noqa: E402
from app.services.analysis.typed_sql_compiler import (  # noqa: E402
    TYPED_SQL_COMPILER_VERSION,
)
from app.services.context.builder import ContextPackageBuilder  # noqa: E402
from app.services.execution_control import IsolatedExecutionCache  # noqa: E402
from app.services.routing_service import RouteDecision  # noqa: E402
from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    IsolatedSystemClient,
    TARGET_PORT,
    TARGET_PROJECT,
)
from phase4_runtime_catalog_projection import (  # noqa: E402
    DATABASE_NAME,
    DATABASE_PORT,
    RuntimeSearchOnlyCatalog,
    StaticProjectionRepository,
    _migration_chain_sha256,
    _put_product_manifest,
    _readiness,
    _source_receipt,
)
from phase5_node1_grounding import _active_manifest, _restore_previous  # noqa: E402
from src.data.governance_contract import (  # noqa: E402
    canonical_json,
    canonical_sha256,
)
from src.data.analysis_capability_contract import (  # noqa: E402
    ANALYSIS_OPERATIONS,
    AnalysisCapabilityContract,
    compile_analysis_capability_contract,
)


GOLD_FILE = (
    ROOT
    / "evals"
    / "single_asset_analysis_gold"
    / "answervice_ko_single_asset.v1.json"
)
CAPABILITY_FILE = (
    ROOT
    / "app"
    / "backend"
    / "contracts"
    / "analysis_capability.single_asset.v1.json"
)
ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
EXPECTED_PREVIOUS_PREFIX = "ANSWERVICE-PHASE5-NODE1:"
EXPECTED_ASSET_FQN = "serving.analytics_v4_3.hotel_operations_daily"
MIGRATION_REVISION = "20260822_33"


class Phase6Error(AcceptanceError):
    """Phase 6 cannot be proved without lowering an execution or isolation Gate."""


class ResultOnlyModel:
    """Allow only Node 3 narration and audit any accidental Node 1/2 call."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_trace: dict[str, object] = {}

    async def normalize_question(self, _payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("node1")
        raise AssertionError("Phase 6 typed-slot path called Node 1")

    async def generate(self, node: str, _payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(node)
        if node != "node3":
            raise AssertionError(f"Phase 6 deterministic compiler called {node}")
        self.last_trace = {
            "node": "node3",
            "model_version": "PHASE6-RESULT-ORACLE-v1.0.0",
            "prompt_id": "phase6.result.oracle",
            "prompt_version": "v1",
            "prompt_hash": "0" * 64,
            "duration_ms": 0,
            "attempts": 1,
            "status": "ACCEPTANCE_SUCCESS",
        }
        # This intentionally contains no result value. ResultStage therefore
        # replaces it with its deterministic grounded narrative.
        return {
            "summary": "승인된 단일 자산 분석 결과입니다.",
            "model_version": "PHASE6-RESULT-ORACLE-v1.0.0",
        }


class AcceptanceDataPlatform:
    """Compose production governance and execution without owning shared clients."""

    def __init__(
        self,
        governance: QueryGovernanceEngine,
        execution: QueryExecutionService,
        catalog: DataHubCatalogClient,
        trino: TrinoAsyncClient,
    ) -> None:
        self._governance = governance
        self._execution = execution
        self._catalog = catalog
        self._trino = trino

    async def search_asset_candidates(
        self, query: str, context: dict[str, Any]
    ) -> AssetCandidateSet:
        return await self._governance.search_asset_candidates(query, context)

    async def resolve_execution_assets(
        self,
        selection: ExecutionAssetSelection,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self._governance.resolve_execution_assets(selection, context)

    async def get_metric_terms(
        self,
        metric_ids: tuple[str, ...],
        context: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        return await self._governance.get_metric_terms(metric_ids, context)

    async def get_asset_schema(
        self,
        urn: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._governance.get_asset_schema(urn, context)

    async def get_active_context_release(self) -> str:
        return await self._governance.active_context_release()

    async def get_catalog_readiness(self) -> tuple[dict[str, str], str | None]:
        return await self._governance.catalog_readiness()

    async def get_product_release_readiness(
        self,
        product_release_id: str,
    ) -> tuple[dict[str, str], str | None, str | None]:
        stages, receipt = await self._governance.catalog_readiness(
            product_release_id
        )
        semantic = (
            await self._governance.active_context_release(product_release_id)
            if receipt == product_release_id
            and all(value == "ready" for value in stages.values())
            else None
        )
        return stages, receipt, semantic

    async def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        return await self._execution.execute(sql, parameters, gate_token)

    async def execute_auxiliary_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        return await self._execution.execute_auxiliary(sql, parameters, gate_token)

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        return await self._execution.get_status(query_id)

    async def cancel_query(self, query_id: str) -> dict[str, Any]:
        return await self._execution.cancel(query_id)

    async def cancel_query_at(
        self, query_id: str, cancel_uri: str
    ) -> dict[str, Any]:
        return await self._execution.cancel_at(query_id, cancel_uri)

    def bind_cancellation(self, check: Callable[[], bool] | None) -> None:
        self._execution.bind_cancellation(check)

    def bind_query_lifecycle(
        self,
        sink: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        self._execution.bind_lifecycle_sink(sink)

    async def get_source_health(self) -> list[dict[str, str]]:
        datahub, trino = await asyncio.gather(
            self._catalog.health(), self._trino.health()
        )
        return [
            {"source": "datahub", "status": "HEALTHY" if datahub else "UNHEALTHY"},
            {"source": "trino", "status": "HEALTHY" if trino else "UNHEALTHY"},
        ]

    async def aclose(self) -> None:
        # Shared clients are closed once by the runner.
        return None


class CountingDataPlatform:
    """Count exact execution attempts while delegating every production boundary."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.execute_count = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        self.execute_count += 1
        return await self._delegate.execute_query(sql, parameters, gate_token)


class FaultExecutionDataPlatform:
    """Inject a typed terminal fault after real catalog/schema validation."""

    def __init__(self, delegate: object, mode: str) -> None:
        if mode not in {"cancelled", "timeout"}:
            raise ValueError("unknown Phase 6 execution fault")
        self._delegate = delegate
        self.mode = mode
        self.execute_count = 0
        self.cancel_count = 0
        self._query_id = f"phase6-{mode}-fault"

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def execute_query(
        self, _sql: str, _parameters: dict[str, Any], _gate_token: str
    ) -> dict[str, Any]:
        self.execute_count += 1
        return {"query_id": self._query_id, "status": self.mode.upper()}

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        if query_id != self._query_id:
            raise ValueError("fault query identity changed")
        return {"query_id": query_id, "status": self.mode.upper()}

    async def cancel_query(self, query_id: str) -> dict[str, Any]:
        if query_id != self._query_id:
            raise ValueError("fault cancel identity changed")
        self.cancel_count += 1
        return {"query_id": query_id, "status": "CANCELLED"}


class DriftSchemaInspector:
    """Fail the execution rebind with a deterministic schema-drift signal."""

    async def verify(self, _datasets: object) -> None:
        raise TrinoSchemaDriftError("Phase 6 injected schema drift")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--target-server", required=True)
    parser.add_argument("--trino-server", required=True)
    parser.add_argument("--trino-ca-file", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    parser.add_argument("--gold-file", type=Path, default=GOLD_FILE)
    parser.add_argument("--capability-file", type=Path, default=CAPABILITY_FILE)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def _validate_boundary(args: argparse.Namespace) -> None:
    if args.target_project != TARGET_PROJECT:
        raise Phase6Error("Phase 6 target project is outside the approved boundary")
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
            raise Phase6Error(f"{label} is outside the approved loopback boundary")
    database = make_url(args.database_url)
    if (
        database.drivername != "postgresql+psycopg"
        or database.host not in {"127.0.0.1", "localhost", "::1"}
        or database.port != DATABASE_PORT
        or database.database != DATABASE_NAME
        or database.username != "postgres"
        or database.password is not None
    ):
        raise Phase6Error("Phase 6 database is outside the isolated boundary")
    if args.timeout <= 0:
        raise Phase6Error("Phase 6 timeout must be positive")
    for supplied, expected, label in (
        (args.env_file, ENV_FILE, "environment"),
        (args.gold_file, GOLD_FILE, "Gold"),
        (args.capability_file, CAPABILITY_FILE, "capability"),
    ):
        try:
            resolved = supplied.resolve(strict=True)
        except OSError as error:
            raise Phase6Error(f"Phase 6 {label} file is unavailable") from error
        if resolved != expected.resolve(strict=True) or not resolved.is_file():
            raise Phase6Error(f"Phase 6 {label} file differs from the sealed path")
    try:
        ca_file = args.trino_ca_file.resolve(strict=True)
    except OSError as error:
        raise Phase6Error("Phase 6 Trino CA is unavailable") from error
    if not args.trino_ca_file.is_absolute() or not ca_file.is_file():
        raise Phase6Error("Phase 6 Trino CA is outside the explicit boundary")


def _environment(path: Path) -> dict[str, str]:
    values = {
        str(key): str(value)
        for key, value in dotenv_values(path).items()
        if value is not None
    }
    required = (
        "DATAHUB_SYSTEM_CLIENT_ID",
        "DATAHUB_SYSTEM_CLIENT_SECRET",
        "TRINO_DATAHUB_USER",
        "TRINO_DATAHUB_PASSWORD",
    )
    if any(not values.get(name, "").strip() for name in required):
        raise Phase6Error("Phase 6 isolated credentials are incomplete")
    ca_value = (
        values.get("DATAHUB_TLS_CA_FILE", "").strip()
        or values.get("DATAHUB_TLS_CA_HOST_FILE", "").strip()
    )
    ca_file = Path(ca_value)
    if not ca_file.is_absolute() or not ca_file.is_file():
        raise Phase6Error("Phase 6 DataHub CA is unavailable")
    values["PHASE6_DATAHUB_CA_FILE"] = str(ca_file.resolve(strict=True))
    return values


def _ast_sha256(sql: str) -> str:
    normalized = parse_one(sql, read="trino").sql(dialect="trino")
    return hashlib.sha256(normalized.encode()).hexdigest()


def _gold(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Phase6Error("Phase 6 Gold cannot be read") from error
    supplied = document.get("content_sha256") if isinstance(document, dict) else None
    payload = (
        {key: value for key, value in document.items() if key != "content_sha256"}
        if isinstance(document, dict)
        else {}
    )
    if supplied != canonical_sha256(payload):
        raise Phase6Error("Phase 6 Gold checksum differs")
    thresholds = document.get("thresholds")
    cases = document.get("cases")
    if (
        document.get("schema_version")
        != "answervice.single_asset_analysis_gold.v1"
        or document.get("status") != "SEALED"
        or document.get("asset_fqn") != EXPECTED_ASSET_FQN
        or not isinstance(thresholds, dict)
        or thresholds.get("min_case_exact_match") != 1.0
        or any(
            thresholds.get(name) != 0
            for name in (
                "max_node1_call_count",
                "max_node2_call_count",
                "max_unapproved_asset_count",
                "max_oracle_mismatch_count",
                "max_failure_artifact_count",
            )
        )
        or not isinstance(cases, list)
        or len(cases) < 8
    ):
        raise Phase6Error("Phase 6 Gold contract or threshold differs")
    identifiers: set[str] = set()
    operations: set[str] = set()
    has_ratio = has_multi = False
    for case in cases:
        if not isinstance(case, dict):
            raise Phase6Error("Phase 6 Gold case is not an object")
        case_id = case.get("case_id")
        metrics = case.get("metric_ids")
        dimensions = case.get("dimension_ids")
        expected_columns = case.get("expected_columns")
        period = case.get("period")
        if (
            not isinstance(case_id, str)
            or case_id in identifiers
            or not isinstance(case.get("query"), str)
            or not case["query"].strip()
            or not isinstance(metrics, list)
            or not 1 <= len(metrics) <= 4
            or len(metrics) != len(set(metrics))
            or not isinstance(dimensions, list)
            or len(dimensions) != len(set(dimensions))
            or not isinstance(expected_columns, list)
            or not expected_columns
            or not isinstance(period, dict)
            or set(period) != {"start", "end_exclusive"}
            or not isinstance(case.get("expected_canonical_sql"), str)
            or not isinstance(case.get("oracle_sql"), str)
            or case.get("expected_ast_sha256")
            != _ast_sha256(case["expected_canonical_sql"])
        ):
            raise Phase6Error("Phase 6 Gold case shape or AST seal differs")
        for sql_name in ("expected_canonical_sql", "oracle_sql"):
            expression = parse_one(case[sql_name], read="trino")
            tables = {
                item.sql(dialect="trino").split(" AS ", 1)[0]
                for item in expression.find_all(exp.Table)
            }
            if (
                not isinstance(expression, exp.Select)
                or tables != {EXPECTED_ASSET_FQN}
                or next(expression.find_all(exp.Join), None) is not None
            ):
                raise Phase6Error("Phase 6 sealed SQL leaves the single asset boundary")
        identifiers.add(case_id)
        operations.add(str(case.get("operation")))
        has_ratio = has_ratio or metrics == ["revpar"]
        has_multi = has_multi or len(metrics) > 1
    if operations != {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    } or not has_ratio or not has_multi:
        raise Phase6Error("Phase 6 Gold capability coverage is incomplete")
    return document


def _capability(
    path: Path,
    active: ActiveRuntimeCatalogProjection,
) -> tuple[dict[str, Any], AnalysisCapabilityContract]:
    """Load and bind the sealed App-owned analysis capability to one catalog."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Phase6Error("Phase 6 capability release is unreadable") from error
    if not isinstance(document, dict):
        raise Phase6Error("Phase 6 capability release must be an object")
    required = {
        "schema_version",
        "status",
        "catalog_release_id",
        "catalog_sha256",
        "canonical_sha256",
        "contract",
        "content_sha256",
    }
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    projection = active.projection
    if (
        set(document) != required
        or document.get("schema_version")
        != "AnswerviceAnalysisCapabilityRelease.v1"
        or document.get("status") != "SEALED"
        or document.get("content_sha256") != canonical_sha256(payload)
        or document.get("catalog_release_id") != projection.catalog_release_id
        or document.get("catalog_sha256") != projection.catalog_sha256
        or document.get("canonical_sha256") != projection.canonical_sha256
    ):
        raise Phase6Error("Phase 6 capability release receipt differs")
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
        raise Phase6Error("Phase 6 capability release is not catalog-bound") from error
    if (
        set(contract.operations) != set(ANALYSIS_OPERATIONS)
        or {item.asset_fqn for item in contract.assets} != {EXPECTED_ASSET_FQN}
    ):
        raise Phase6Error("Phase 6 capability scope differs")
    return document, contract


def _phase6_manifest(
    active: ActiveRuntimeCatalogProjection,
    previous: ProductReleaseEvidenceManifest,
    gold: Mapping[str, object],
    capability_sha256: str,
) -> ProductReleaseEvidenceManifest:
    source, created_at = _source_receipt()
    projection = active.projection
    evidence = ProductReleaseEvidence(
        source=source,
        images=previous.evidence.images,
        migration=MigrationReceipt(
            revision=MIGRATION_REVISION,
            chain_sha256=_migration_chain_sha256(),
        ),
        model=previous.evidence.model,
        catalog=CatalogReceipt(
            release_id=projection.catalog_release_id,
            manifest_sha256=projection.manifest_sha256,
            projection_sha256=projection.projection_sha256,
        ),
        release_vector=ProductReleaseVector(
            data_release_id=projection.catalog_release_id,
            semantic_release_id=projection.catalog_release_id,
            prompt_release_id=previous.evidence.release_vector.prompt_release_id,
            policy_release_id=projection.release.policy_version,
            runtime_release_id="PHASE6-RUNTIME-v1:"
            + canonical_sha256(
                {
                    "projection_sha256": projection.projection_sha256,
                    "compiler": TYPED_SQL_COMPILER_VERSION,
                    "analysis_capability_sha256": capability_sha256,
                }
            ),
        ),
    )
    identity = canonical_sha256(
        {
            "phase": "6",
            "contract": "same_asset_single_turn.v1",
            "compiler": TYPED_SQL_COMPILER_VERSION,
            "gold_sha256": gold["content_sha256"],
            "analysis_capability_sha256": capability_sha256,
            "evidence": evidence.model_dump(mode="json"),
        }
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=f"ANSWERVICE-PHASE6-SINGLE-ASSET:{identity}",
        evidence=evidence,
        created_at=created_at,
    )


def _payload(case: Mapping[str, object]) -> AnalysisRequest:
    metric_ids = tuple(map(str, case["metric_ids"]))
    period = case["period"]
    comparison = case.get("comparison_period")
    if not isinstance(period, Mapping):
        raise Phase6Error("Phase 6 case period is invalid")
    if comparison is not None and not isinstance(comparison, Mapping):
        raise Phase6Error("Phase 6 case comparison period is invalid")
    slots = ResolvedSlots(
        metric_id=metric_ids[0] if len(metric_ids) == 1 else None,
        metric_ids=metric_ids,
        dimension_ids=tuple(map(str, case["dimension_ids"])),
        user_filters=tuple(
            dict(item)
            for item in case.get("user_filters", ())
            if isinstance(item, Mapping)
        ),
        period_start=str(period["start"]),
        period_end_exclusive=str(period["end_exclusive"]),
        comparison_period_start=(
            str(comparison["start"]) if comparison is not None else None
        ),
        comparison_period_end_exclusive=(
            str(comparison["end_exclusive"])
            if comparison is not None
            else None
        ),
        analysis_operation=str(case["operation"]),
        result_limit=(
            int(case["result_limit"])
            if case.get("result_limit") is not None
            else None
        ),
    )
    return AnalysisRequest(question=str(case["query"]), resolved_slots=slots)


async def _pipeline_run(
    *,
    platform: object,
    model: ResultOnlyModel,
    repository: PostgresAnalysisRepository,
    owner_id: UUID,
    manifest: ProductReleaseEvidenceManifest,
    semantic_release_id: str,
    case: Mapping[str, object],
    as_of: date,
    trace_prefix: str,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[AnalysisResponse, dict[str, Any], RequestContext]:
    context = RequestContext(
        trace_id=f"{trace_prefix}-{case['case_id']}",
        user_id=owner_id,
        role=Role.ANALYST,
        as_of=as_of,
        permission_snapshot_id="phase6-isolated-permission",
        product_release_id=manifest.product_release_id,
        semantic_release_id=semantic_release_id,
    )
    payload = _payload(case)
    await repository.begin_request(payload.question, payload.parameters, context)
    execution: dict[str, Any] = {}
    bind_lifecycle = getattr(platform, "bind_query_lifecycle", None)
    if callable(bind_lifecycle):
        bind_lifecycle(
            lambda event: repository.record_query_lifecycle(
                context.request_id, event
            )
        )
    try:
        response = await AnalysisService(
            platform,
            model,
            context_builder=ContextPackageBuilder(),
            cache=IsolatedExecutionCache(),
        ).analyze(
            payload,
            context,
            RouteDecision(RouteType.GENERAL, None, True, True),
            execution_sink=execution.update,
            cancel_check=cancel_check,
        )
    finally:
        if callable(bind_lifecycle):
            bind_lifecycle(None)
    await repository.finish_run(context.request_id, response, execution)
    return response, execution, context


async def _collect_query(
    client: TrinoAsyncClient,
    sql: str,
    timeout_seconds: float,
) -> tuple[tuple[str, ...], list[dict[str, object]]]:
    deadline = monotonic() + timeout_seconds
    page = await client.execute(sql, deadline=deadline)
    columns = page.columns
    rows = list(page.rows)
    for _ in range(100):
        if not page.next_uri:
            break
        page = await client.next_page(page.next_uri, deadline=deadline)
        columns = page.columns or columns
        rows.extend(page.rows)
    else:
        raise Phase6Error("Phase 6 oracle exceeded the bounded page count")
    if page.next_uri or page.state != "FINISHED" or len(rows) > 1_000:
        raise Phase6Error("Phase 6 oracle did not finish inside its bounds")
    return columns, [dict(zip(columns, row, strict=True)) for row in rows]


def _canonical_rows(rows: list[dict[str, object]]) -> str:
    encoded = [
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in rows
    ]
    return canonical_json(sorted(encoded))


async def _evaluate_case(
    *,
    platform: CountingDataPlatform,
    model: ResultOnlyModel,
    repository: PostgresAnalysisRepository,
    owner_id: UUID,
    manifest: ProductReleaseEvidenceManifest,
    candidate: ActiveRuntimeCatalogProjection,
    case: Mapping[str, object],
    as_of: date,
    trace_prefix: str,
    trino: TrinoAsyncClient,
    timeout_seconds: float,
) -> dict[str, object]:
    before = platform.execute_count
    response, execution, context = await _pipeline_run(
        platform=platform,
        model=model,
        repository=repository,
        owner_id=owner_id,
        manifest=manifest,
        semantic_release_id=candidate.projection.catalog_release_id,
        case=case,
        as_of=as_of,
        trace_prefix=trace_prefix,
    )
    if (
        response.data.status is not AnalysisStatus.SUCCEEDED
        or response.data.artifact is None
        or response.data.result is None
        or platform.execute_count != before + 1
        or set(execution) != {"plan", "query", "package"}
    ):
        error_code = (
            response.error.code.value
            if response.error is not None
            else None
        )
        raise Phase6Error(
            "Phase 6 case failed before oracle comparison: "
            f"{case['case_id']}; status={response.data.status.value}; "
            f"error_code={error_code}; execute_delta={platform.execute_count - before}; "
            f"execution_keys={','.join(sorted(execution)) or 'none'}"
        )
    plan = execution["plan"]
    query = execution["query"]
    package = execution["package"]
    if (
        plan.get("plan_source") != "typed_sql_compiler"
        or plan.get("model_version") != TYPED_SQL_COMPILER_VERSION
        or _ast_sha256(str(plan.get("sql") or ""))
        != case["expected_ast_sha256"]
        or plan.get("ast_evidence", {}).get("projection_aliases")
        != case["expected_columns"]
    ):
        raise Phase6Error(f"Phase 6 sealed AST differs: {case['case_id']}")
    expression = parse_one(str(plan["sql"]), read="trino")
    tables = {
        item.sql(dialect="trino").split(" AS ", 1)[0]
        for item in expression.find_all(exp.Table)
    }
    if tables != {EXPECTED_ASSET_FQN} or next(
        expression.find_all(exp.Join), None
    ) is not None:
        raise Phase6Error(f"Phase 6 case left the single asset: {case['case_id']}")
    oracle_columns, oracle_rows = await _collect_query(
        trino, str(case["oracle_sql"]), timeout_seconds
    )
    pipeline_rows = [dict(row) for row in query.get("rows", ())]
    if (
        oracle_columns != tuple(case["expected_columns"])
        or _canonical_rows(pipeline_rows) != _canonical_rows(oracle_rows)
    ):
        raise Phase6Error(f"Phase 6 Trino result oracle differs: {case['case_id']}")
    evidence = response.data.result.evidence
    if (
        evidence.product_release_id != manifest.product_release_id
        or evidence.context_release != candidate.projection.catalog_release_id
        or evidence.query_id != response.data.artifact.query_id
        or evidence.artifact_id != response.data.artifact.artifact_id
        or response.data.artifact.context_hash != package.package_hash
    ):
        raise Phase6Error(f"Phase 6 Artifact receipt differs: {case['case_id']}")
    return {
        "case_id": case["case_id"],
        "exact": True,
        "operation": case["operation"],
        "metric_ids": list(case["metric_ids"]),
        "row_count": len(pipeline_rows),
        "ast_sha256": case["expected_ast_sha256"],
        "result_sha256": hashlib.sha256(
            _canonical_rows(pipeline_rows).encode()
        ).hexdigest(),
        "request_id": str(context.request_id),
        "artifact_id": str(response.data.artifact.artifact_id),
    }


def _fault_case(
    case_id: str,
    *,
    metric_ids: tuple[str, ...] = ("room_revenue",),
    operation: str = "aggregate",
    start: str = "2025-08-01",
    end: str = "2025-09-01",
    comparison: tuple[str, str] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "query": f"Phase 6 fault probe {case_id}",
        "metric_ids": list(metric_ids),
        "dimension_ids": [],
        "operation": operation,
        "result_limit": None,
        "period": {"start": start, "end_exclusive": end},
        "comparison_period": (
            {"start": comparison[0], "end_exclusive": comparison[1]}
            if comparison
            else None
        ),
    }


async def _fault_gates(
    *,
    base_platform: CountingDataPlatform,
    drift_platform: object,
    model: ResultOnlyModel,
    repository: PostgresAnalysisRepository,
    owner_id: UUID,
    manifest: ProductReleaseEvidenceManifest,
    candidate: ActiveRuntimeCatalogProjection,
    as_of: date,
    trace_prefix: str,
) -> dict[str, object]:
    results: dict[str, object] = {}

    # Pre-context clarification must not search or execute.
    clarification_case = _fault_case("FAULT-CLARIFICATION")
    clarification_case["metric_ids"] = []
    clarification_payload = AnalysisRequest(
        question="분석해줘",
        resolved_slots=ResolvedSlots(
            period_start="2025-08-01",
            period_end_exclusive="2025-09-01",
            analysis_operation="aggregate",
        ),
    )
    clarification_context = RequestContext(
        trace_id=f"{trace_prefix}-FAULT-CLARIFICATION",
        user_id=owner_id,
        role=Role.ANALYST,
        as_of=as_of,
        permission_snapshot_id="phase6-isolated-permission",
        product_release_id=manifest.product_release_id,
        semantic_release_id=candidate.projection.catalog_release_id,
    )
    await repository.begin_request(
        clarification_payload.question,
        clarification_payload.parameters,
        clarification_context,
    )
    before = base_platform.execute_count
    clarification = await AnalysisService(
        base_platform, model, cache=IsolatedExecutionCache()
    ).analyze(
        clarification_payload,
        clarification_context,
        RouteDecision(RouteType.GENERAL, None, True, True),
    )
    await repository.finish_run(clarification_context.request_id, clarification, {})
    if (
        clarification.data.status is not AnalysisStatus.CLARIFICATION_REQUIRED
        or clarification.data.artifact is not None
        or base_platform.execute_count != before
    ):
        raise Phase6Error("Phase 6 clarification closure failed")
    results["clarification"] = {
        "status": clarification.data.status.value,
        "execution_count": 0,
        "artifact_count": 0,
    }

    # Ratio period comparison is explicitly outside the deterministic contract.
    unsupported_case = _fault_case(
        "FAULT-UNSUPPORTED",
        metric_ids=("revpar",),
        operation="period_comparison",
        comparison=("2025-07-01", "2025-08-01"),
    )
    before = base_platform.execute_count
    unsupported, _, _ = await _pipeline_run(
        platform=base_platform,
        model=model,
        repository=repository,
        owner_id=owner_id,
        manifest=manifest,
        semantic_release_id=candidate.projection.catalog_release_id,
        case=unsupported_case,
        as_of=as_of,
        trace_prefix=trace_prefix,
    )
    if (
        unsupported.data.status is not AnalysisStatus.BLOCKED
        or unsupported.error is None
        or unsupported.error.code is not ErrorCode.SEMANTIC_CONTRACT_INVALID
        or unsupported.data.artifact is not None
        or base_platform.execute_count != before
    ):
        raise Phase6Error("Phase 6 unsupported closure failed")
    results["unsupported"] = {
        "status": unsupported.data.status.value,
        "execution_count": 0,
        "artifact_count": 0,
    }

    for mode, expected_status, expected_error in (
        ("cancelled", AnalysisStatus.CANCELLED, ErrorCode.REQUEST_CANCELLED),
        ("timeout", AnalysisStatus.FAILED, ErrorCode.QUERY_TIMEOUT),
    ):
        fault = FaultExecutionDataPlatform(base_platform, mode)
        response, _, _ = await _pipeline_run(
            platform=fault,
            model=model,
            repository=repository,
            owner_id=owner_id,
            manifest=manifest,
            semantic_release_id=candidate.projection.catalog_release_id,
            case=_fault_case(f"FAULT-{mode.upper()}"),
            as_of=as_of,
            trace_prefix=trace_prefix,
        )
        if (
            response.data.status is not expected_status
            or response.error is None
            or response.error.code is not expected_error
            or response.data.artifact is not None
            or fault.execute_count != 1
            or (mode == "timeout" and fault.cancel_count != 1)
        ):
            raise Phase6Error(f"Phase 6 {mode} fault closure failed")
        results[mode] = {
            "status": response.data.status.value,
            "execution_count": fault.execute_count,
            "cancel_count": fault.cancel_count,
            "artifact_count": 0,
        }

    # A real aggregate over a known-empty historical window becomes an empty,
    # evidence-complete Artifact rather than a fabricated scalar.
    empty_case = _fault_case(
        "FAULT-EMPTY",
        # ClickHouse Date connector의 지원 하한 안이면서 source seed보다 앞선
        # 구간을 사용한다. 1900년은 empty가 아니라 connector query error다.
        start="1970-01-01",
        end="1970-02-01",
    )
    before = base_platform.execute_count
    empty, empty_execution, _ = await _pipeline_run(
        platform=base_platform,
        model=model,
        repository=repository,
        owner_id=owner_id,
        manifest=manifest,
        semantic_release_id=candidate.projection.catalog_release_id,
        case=empty_case,
        as_of=as_of,
        trace_prefix=trace_prefix,
    )
    if (
        empty.data.status is not AnalysisStatus.SUCCEEDED
        or empty.data.artifact is None
        or empty.data.result is None
        or empty.data.result.table is None
        or empty.data.result.table.rows
        or empty_execution.get("query", {}).get("rows")
        or base_platform.execute_count != before + 1
    ):
        raise Phase6Error("Phase 6 empty-result normalization failed")
    results["empty"] = {
        "status": empty.data.status.value,
        "execution_count": 1,
        "row_count": 0,
        "artifact_count": 1,
    }

    before = base_platform.execute_count
    drift, _, _ = await _pipeline_run(
        platform=drift_platform,
        model=model,
        repository=repository,
        owner_id=owner_id,
        manifest=manifest,
        semantic_release_id=candidate.projection.catalog_release_id,
        case=_fault_case("FAULT-SCHEMA-DRIFT"),
        as_of=as_of,
        trace_prefix=trace_prefix,
    )
    if (
        drift.data.status not in {AnalysisStatus.FAILED, AnalysisStatus.BLOCKED}
        or drift.data.artifact is not None
        or base_platform.execute_count != before
    ):
        raise Phase6Error("Phase 6 schema-drift closure failed")
    results["schema_drift"] = {
        "status": drift.data.status.value,
        "execution_count": 0,
        "artifact_count": 0,
    }
    return results


async def _persistence_readback(
    sessionmaker,
    trace_prefix: str,
    product_release_id: str,
) -> dict[str, int]:
    try:
        async with sessionmaker() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          count(DISTINCT r.request_id) AS request_count,
                          count(DISTINCT q.query_execution_id) AS query_count,
                          count(DISTINCT a.artifact_id) AS artifact_count,
                          count(DISTINCT b.object_id) AS artifact_binding_count,
                          count(DISTINCT CASE WHEN r.status = 'SUCCEEDED'
                                             THEN r.request_id END) AS success_count
                        FROM chat.analysis_requests r
                        LEFT JOIN query.query_executions q
                          ON q.request_id = r.request_id
                        LEFT JOIN artifact.analysis_artifacts a
                          ON a.request_id = r.request_id
                        LEFT JOIN governance.product_release_bindings b
                          ON b.object_kind = 'ARTIFACT'
                         AND b.object_id = a.artifact_id::text
                         AND b.product_release_id = :product_release_id
                        WHERE r.trace_id LIKE :trace_pattern
                          AND r.product_release_id = :product_release_id
                        """
                    ),
                    {
                        "trace_pattern": f"{trace_prefix}-%",
                        "product_release_id": product_release_id,
                    },
                )
            ).mappings().one()
        return {name: int(value) for name, value in row.items()}
    except SQLAlchemyError as error:
        raise Phase6Error("Phase 6 persistence read-back failed") from error


async def _activation_receipts(
    sessionmaker,
    product_release_id: str,
) -> list[dict[str, object]]:
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT action, expected_generation, resulting_generation
                    FROM governance.runtime_catalog_activation_receipts
                    WHERE target_product_release_id = :product_release_id
                       OR previous_product_release_id = :product_release_id
                    ORDER BY created_at, activation_id
                    """
                ),
                {"product_release_id": product_release_id},
            )
        ).mappings().all()
    return [dict(row) for row in rows]


async def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_boundary(args)
    environment = _environment(args.env_file)
    gold = _gold(args.gold_file)
    as_of = date.fromisoformat(str(gold["as_of"]))
    sessionmaker = get_sessionmaker(args.database_url)
    projection_repository = PostgresRuntimeCatalogProjectionRepository(sessionmaker)
    previous_active = await projection_repository.load_active()
    if (
        previous_active.generation < 7
        or not previous_active.product_release_id.startswith(EXPECTED_PREVIOUS_PREFIX)
        or previous_active.projection.source_selection.get("authority_mode")
        != "NATIVE_PRIORITY"
    ):
        raise Phase6Error("Phase 6 requires the verified Phase 5 active pointer")
    previous_manifest = await _active_manifest(
        sessionmaker, previous_active.product_release_id
    )
    capability_document, analysis_capability = _capability(
        args.capability_file,
        previous_active,
    )
    manifest = _phase6_manifest(
        previous_active,
        previous_manifest,
        gold,
        str(capability_document["content_sha256"]),
    )
    await _put_product_manifest(sessionmaker, manifest)
    candidate = await projection_repository.load_candidate(
        previous_active.projection.projection_id,
        manifest.product_release_id,
    )

    ca_file = Path(environment["PHASE6_DATAHUB_CA_FILE"])
    account = token = token_id = None
    catalog: DataHubCatalogClient | None = None
    trino: TrinoAsyncClient | None = None
    engines: list[QueryGovernanceEngine] = []
    cleanup_errors: list[BaseException] = []
    activated = False
    try:
        async with IsolatedSystemClient(
            args.target_server,
            ca_file=ca_file,
            client_id=environment["DATAHUB_SYSTEM_CLIENT_ID"],
            client_secret=environment["DATAHUB_SYSTEM_CLIENT_SECRET"],
            timeout_seconds=args.timeout,
        ) as system:
            try:
                account = await system.create_temporary_service_account()
                token, token_id = await system.create_temporary_access_token(account)
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
                    raise Phase6Error(
                        f"target DataHub read identity failed: {error.category}"
                    ) from error
                if not healthy:
                    raise Phase6Error("temporary target DataHub identity is unhealthy")
                trino = TrinoAsyncClient(
                    args.trino_server,
                    environment["TRINO_DATAHUB_USER"],
                    environment["TRINO_DATAHUB_PASSWORD"],
                    ca_file=args.trino_ca_file,
                    request_timeout_seconds=args.timeout,
                )
                schema = TrinoSchemaInspector(trino, timeout_seconds=args.timeout)
                runtime_catalog = RuntimeSearchOnlyCatalog(catalog)
                candidate_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    schema,
                    expected_context_release=candidate.projection.catalog_release_id,
                    search_mode="datahub_lexical",
                    projection_repository=StaticProjectionRepository(candidate),
                    analysis_capability=analysis_capability,
                )
                engines.append(candidate_engine)
                readiness, readiness_receipt, canary_latency = await _readiness(
                    candidate_engine
                )
                if readiness_receipt != manifest.product_release_id:
                    raise Phase6Error("Phase 6 candidate readiness receipt differs")
                pointer_after_canary = await projection_repository.load_active()
                if (
                    pointer_after_canary.product_release_id
                    != previous_active.product_release_id
                    or pointer_after_canary.generation != previous_active.generation
                ):
                    raise Phase6Error("Phase 6 canary changed the active pointer")

                execution = QueryExecutionService(
                    trino,
                    timeout_seconds=args.timeout,
                    state_ttl_seconds=300,
                    state_max_entries=200,
                )
                candidate_platform = CountingDataPlatform(
                    AcceptanceDataPlatform(
                        candidate_engine, execution, catalog, trino
                    )
                )
                drift_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    DriftSchemaInspector(),
                    expected_context_release=candidate.projection.catalog_release_id,
                    search_mode="datahub_lexical",
                    projection_repository=StaticProjectionRepository(candidate),
                    analysis_capability=analysis_capability,
                )
                engines.append(drift_engine)
                drift_platform = AcceptanceDataPlatform(
                    drift_engine,
                    QueryExecutionService(trino, timeout_seconds=args.timeout),
                    catalog,
                    trino,
                )
                owner_id = uuid4()
                repository = PostgresAnalysisRepository(
                    args.database_url,
                    owner_id,
                    session_factory=sessionmaker,
                )
                model = ResultOnlyModel()
                trace_prefix = f"phase6-{uuid4().hex[:12]}"
                evaluations = []
                for case in gold["cases"]:
                    evaluations.append(
                        await _evaluate_case(
                            platform=candidate_platform,
                            model=model,
                            repository=repository,
                            owner_id=owner_id,
                            manifest=manifest,
                            candidate=candidate,
                            case=case,
                            as_of=as_of,
                            trace_prefix=trace_prefix,
                            trino=trino,
                            timeout_seconds=args.timeout,
                        )
                    )
                exact_count = sum(item["exact"] is True for item in evaluations)
                exact_rate = exact_count / len(evaluations)
                if exact_rate < gold["thresholds"]["min_case_exact_match"]:
                    raise Phase6Error("Phase 6 exact case threshold failed")

                faults = await _fault_gates(
                    base_platform=candidate_platform,
                    drift_platform=drift_platform,
                    model=model,
                    repository=repository,
                    owner_id=owner_id,
                    manifest=manifest,
                    candidate=candidate,
                    as_of=as_of,
                    trace_prefix=trace_prefix,
                )
                if "node1" in model.calls or "node2" in model.calls or "node2_repair" in model.calls:
                    raise Phase6Error("Phase 6 deterministic path called Node 1 or Node 2")

                activated_pointer = await projection_repository.activate(
                    projection_id=candidate.projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=previous_active.generation,
                    action="ACTIVATE",
                    actor="phase6-acceptance",
                    reason="sealed single-asset AST and Trino oracle passed",
                )
                activated = True
                rolled_back = await projection_repository.activate(
                    projection_id=previous_active.projection.projection_id,
                    product_release_id=previous_active.product_release_id,
                    expected_generation=activated_pointer.generation,
                    action="ROLLBACK",
                    actor="phase6-acceptance",
                    reason="verify isolated Phase 6 rollback",
                )
                activated = False
                final_active = await projection_repository.activate(
                    projection_id=candidate.projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=rolled_back.generation,
                    action="ACTIVATE",
                    actor="phase6-acceptance",
                    reason="reactivate verified Phase 6 release",
                )
                activated = True

                active_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    schema,
                    expected_context_release=candidate.projection.catalog_release_id,
                    search_mode="datahub_lexical",
                    projection_repository=projection_repository,
                    analysis_capability=analysis_capability,
                )
                engines.append(active_engine)
                active_readiness, active_receipt, active_latency = await _readiness(
                    active_engine
                )
                if active_receipt != manifest.product_release_id:
                    raise Phase6Error("Phase 6 active readiness receipt differs")
                active_platform = CountingDataPlatform(
                    AcceptanceDataPlatform(
                        active_engine,
                        QueryExecutionService(trino, timeout_seconds=args.timeout),
                        catalog,
                        trino,
                    )
                )
                active_case = await _evaluate_case(
                    platform=active_platform,
                    model=model,
                    repository=repository,
                    owner_id=owner_id,
                    manifest=manifest,
                    candidate=final_active,
                    case=gold["cases"][0],
                    as_of=as_of,
                    trace_prefix=trace_prefix,
                    trino=trino,
                    timeout_seconds=args.timeout,
                )
                persisted = await _persistence_readback(
                    sessionmaker, trace_prefix, manifest.product_release_id
                )
                expected_successes = len(gold["cases"]) + 2  # empty + active replay
                expected_requests = len(gold["cases"]) + 6 + 1  # six faults + replay
                if persisted != {
                    "request_count": expected_requests,
                    "query_count": expected_successes,
                    "artifact_count": expected_successes,
                    "artifact_binding_count": expected_successes,
                    "success_count": expected_successes,
                }:
                    raise Phase6Error(
                        "Phase 6 persistence cardinality differs: "
                        + canonical_json(persisted)
                    )
                receipts = await _activation_receipts(
                    sessionmaker, manifest.product_release_id
                )
                tail = receipts[-3:]
                if [item["action"] for item in tail] != [
                    "ACTIVATE",
                    "ROLLBACK",
                    "ACTIVATE",
                ]:
                    raise Phase6Error("Phase 6 activation receipt sequence differs")
                verified_active = await projection_repository.load_active()
                if (
                    verified_active.product_release_id != manifest.product_release_id
                    or verified_active.generation != final_active.generation
                ):
                    raise Phase6Error("Phase 6 final active pointer differs")
                return {
                    "status": "PHASE6_SINGLE_ASSET_ANALYSIS_PASSED",
                    "target_project": args.target_project,
                    "database": DATABASE_NAME,
                    "gold_dataset_id": gold["dataset_id"],
                    "gold_content_sha256": gold["content_sha256"],
                    "analysis_capability_sha256": capability_document[
                        "content_sha256"
                    ],
                    "case_count": len(evaluations),
                    "exact_count": exact_count,
                    "exact_rate": exact_rate,
                    "evaluations": evaluations,
                    "typed_sql_compiler_version": TYPED_SQL_COMPILER_VERSION,
                    "node1_call_count": model.calls.count("node1"),
                    "node2_call_count": sum(
                        model.calls.count(name) for name in ("node2", "node2_repair")
                    ),
                    "node3_call_count": model.calls.count("node3"),
                    "candidate_execution_count": candidate_platform.execute_count,
                    "faults": faults,
                    "persistence": persisted,
                    "candidate_canary": {
                        "stages": readiness,
                        "latency_ms": canary_latency,
                        "pointer_unchanged": True,
                    },
                    "active_readiness": {
                        "stages": active_readiness,
                        "latency_ms": active_latency,
                    },
                    "activation_receipts": tail,
                    "final_generation": verified_active.generation,
                    "final_product_release_id": verified_active.product_release_id,
                    "active_replay": active_case,
                    "runtime_full_scroll_attempt_count": runtime_catalog.full_read_attempt_count,
                    "bounded_search_request_count": runtime_catalog.search_request_count,
                    "temporary_read_token_revoked": True,
                    "temporary_service_account_deleted": True,
                }
            except BaseException:
                if activated:
                    try:
                        await _restore_previous(projection_repository, previous_active)
                        activated = False
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
                if token_id is not None:
                    try:
                        await system.revoke_access_token(token_id)
                    except BaseException as error:
                        cleanup_errors.append(error)
                if account is not None:
                    try:
                        await system.delete_service_account(account)
                    except BaseException as error:
                        cleanup_errors.append(error)
    finally:
        if cleanup_errors:
            raise Phase6Error("Phase 6 temporary resource cleanup failed") from cleanup_errors[0]


def _run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    """Run psycopg on a Windows-compatible selector event loop."""

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(run(args))
    return asyncio.run(run(args))


def main(argv: list[str] | None = None) -> int:
    try:
        result = _run_acceptance(parse_args(argv))
    except (AcceptanceError, AdapterError, OSError, RuntimeError, ValueError) as error:
        output = {"status": "FAILED", "error_type": type(error).__name__}
        if isinstance(
            error,
            (AcceptanceError, RuntimeCatalogRepositoryError, RuntimeError, ValueError),
        ):
            output["reason"] = " ".join(str(error).split())[:500]
        print(json.dumps(output, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
