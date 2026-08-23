"""격리 환경에서 Phase 8 native semantic shadow Gate를 실행한다.

현재 DataHub와 Trino는 읽기 전용 runtime source로 사용한다. 모든 metadata mutation은
``answervice-phase2b-datahub``의 38081 GMS에, release activation은 55440 acceptance DB에만
한정하며 native semantic metadata를 Backend 실행 권한으로 전환하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from time import monotonic, time_ns
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url


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
from app.adapters.model_adapter import ContractModelAdapter  # noqa: E402
from app.adapters.query_execution import QueryExecutionService  # noqa: E402
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ActiveRuntimeCatalogProjection,
    PostgresRuntimeCatalogProjectionRepository,
)
from app.adapters.trino_async import AdapterError, TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import TrinoSchemaInspector  # noqa: E402
from app.capability_contracts import ProductReleaseEvidenceManifest  # noqa: E402
from app.database import get_sessionmaker  # noqa: E402
from app.services.analysis.pipeline_support import PipelineSupport  # noqa: E402
from app.services.context.builder import ContextPackageBuilder  # noqa: E402
from metadata_rest import assert_contains, aspect_value  # noqa: E402
from metadata_wire import validated_audit_stamp  # noqa: E402
from native_metric_shadow import iter_native_metric_aspects  # noqa: E402
from native_semantic_publication import (  # noqa: E402
    grouped_native_semantic_aspects,
    native_semantic_status_targets,
    probe_native_semantic_model,
    publish_native_semantic_shadow,
    relationship_capability_probe_aspects,
    restore_phase3_metric_aspects,
    set_native_semantic_removed,
    verify_native_semantic_shadow,
)
from native_semantic_shadow import (  # noqa: E402
    NativeSemanticShadowError,
    native_semantic_shadow_projection,
    semantic_model_urn,
)
from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    IsolatedSystemClient,
    TARGET_PORT,
    TARGET_PROJECT,
)
from phase3b_native_metric_shadow import RetryingIsolatedClient  # noqa: E402
from phase4_runtime_catalog_projection import (  # noqa: E402
    DATABASE_NAME,
    DATABASE_PORT,
    RuntimeSearchOnlyCatalog,
    StaticProjectionRepository,
    _put_product_manifest,
    _readiness,
    _source_receipt,
)
from phase5_node1_grounding import (  # noqa: E402
    AuditedNode1Model,
    CountingDataPlatform as Node1CountingDataPlatform,
    _active_manifest,
    _environment,
    _evaluate_case as _evaluate_node1_case,
    _gold as _node1_gold,
    _restore_previous,
)
from phase6_single_asset_analysis import (  # noqa: E402
    CAPABILITY_FILE,
    GOLD_FILE as ANALYSIS_GOLD_FILE,
    AcceptanceDataPlatform,
    CountingDataPlatform as AnalysisCountingDataPlatform,
    ResultOnlyModel,
    _activation_receipts,
    _capability,
    _evaluate_case as _evaluate_analysis_case,
    _gold as _analysis_gold,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
NODE1_GOLD_FILE = (
    ROOT / "evals" / "node1_grounding_gold" / "answervice_ko_node1.v1.json"
)
EXPECTED_PREVIOUS_PREFIX = "ANSWERVICE-PHASE7-BOUNDED-MULTITURN:"
PHASE8_PREFIX = "ANSWERVICE-PHASE8-NATIVE-SEMANTIC:"
_MODEL_NAME = "Answervice Analysis Semantic Model"
_SEMANTIC_SEARCH = """
query Phase8SemanticModelSearch($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    total
    count
    start
    searchResults { entity { urn type } }
  }
}
""".strip()


class Phase8Error(AcceptanceError):
    """Phase 8 equality·비회귀·rollback Gate를 낮추지 않고 증명할 수 없음을 알린다."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """격리 경계와 bounded timeout만 받는 Phase 8 CLI 인자를 해석한다."""

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
        raise Phase8Error("Phase 8 target project is outside the approved boundary")
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
            raise Phase8Error(f"{label} is outside the approved loopback boundary")
    database = make_url(args.database_url)
    if (
        database.drivername != "postgresql+psycopg"
        or database.host not in {"127.0.0.1", "localhost", "::1"}
        or database.port != DATABASE_PORT
        or database.database != DATABASE_NAME
        or database.username != "postgres"
        or database.password is not None
    ):
        raise Phase8Error("Phase 8 database is outside the isolated boundary")
    if args.timeout <= 0 or args.verify_timeout <= 0:
        raise Phase8Error("Phase 8 timeout must be positive")
    for supplied, expected, label in (
        (args.env_file, ENV_FILE, "environment"),
        (args.trino_ca_file, args.trino_ca_file, "Trino CA"),
    ):
        try:
            resolved = supplied.resolve(strict=True)
        except OSError as error:
            raise Phase8Error(f"Phase 8 {label} file is unavailable") from error
        if not resolved.is_file() or (
            label == "environment" and resolved != expected.resolve(strict=True)
        ):
            raise Phase8Error(f"Phase 8 {label} file differs from the sealed boundary")


def _phase8_manifest(
    active: ActiveRuntimeCatalogProjection,
    previous: ProductReleaseEvidenceManifest,
    projection: Mapping[str, Any],
) -> ProductReleaseEvidenceManifest:
    """기존 product evidence와 Phase 8 shadow receipt를 한 immutable ID로 결속한다."""

    _source, created_at = _source_receipt()
    identity = canonical_sha256(
        {
            "phase": "8",
            "previous_product_release_id": previous.product_release_id,
            "previous_manifest_sha256": previous.manifest_sha256,
            "runtime_projection_sha256": active.projection.projection_sha256,
            "native_semantic_projection_sha256": projection["projection_sha256"],
            "native_semantic_membership_sha256": projection[
                "release_membership_sha256"
            ],
            "legacy_surface_sha256": projection["legacy_surface_sha256"],
            "compiled_native_surface_sha256": projection[
                "compiled_native_surface_sha256"
            ],
            "runtime_authority_activated": False,
        }
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=f"{PHASE8_PREFIX}{identity}",
        evidence=previous.evidence,
        created_at=created_at,
    )


async def _preflight_identities(
    client: Any,
    bundle: Mapping[str, Any],
) -> dict[str, int]:
    key_names = {
        "structuredProperty": "structuredPropertyKey",
        "semanticModel": "semanticModelKey",
        "dataset": "datasetKey",
        "schemaField": "schemaFieldKey",
        "metric": "metricKey",
    }
    absent = matching = 0
    for (entity_type, urn), aspects in grouped_native_semantic_aspects(bundle).items():
        key_name = key_names[entity_type]
        expected = aspects[key_name]
        try:
            entity = await client.get_entity(urn, (key_name,))
        except AcceptanceError as error:
            if str(error) == "isolated DataHub request failed with HTTP 404":
                absent += 1
                continue
            raise
        try:
            assert_contains(aspect_value(entity, key_name), expected, f"{urn}.{key_name}")
        except ValueError as error:
            raise Phase8Error("stable native semantic URN is occupied") from error
        matching += 1
    return {"absent": absent, "matching": matching}


async def _wait_removed(
    client: Any,
    targets: list[tuple[str, str]],
    *,
    removed: bool,
    timeout_seconds: float,
) -> None:
    deadline = monotonic() + timeout_seconds
    while True:
        exact = True
        for _entity_type, urn in targets:
            try:
                entity = await client.get_entity(urn, ("status",))
                if aspect_value(entity, "status").get("removed") is not removed:
                    exact = False
            except (AcceptanceError, ValueError):
                exact = False
        if exact:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Phase8Error("native semantic retirement state did not converge")
        await asyncio.sleep(min(0.5, remaining))


async def _semantic_search(client: Any, query: str) -> set[str]:
    payload = await client.graphql(
        _SEMANTIC_SEARCH,
        {
            "input": {
                "types": ["SEMANTIC_MODEL"],
                "query": query,
                "start": 0,
                "count": 20,
            }
        },
    )
    page = payload.get("data", {}).get("searchAcrossEntities")
    rows = page.get("searchResults") if isinstance(page, Mapping) else None
    if (
        not isinstance(page, Mapping)
        or not isinstance(rows, list)
        or page.get("start") != 0
        or not isinstance(page.get("total"), int)
        or not isinstance(page.get("count"), int)
        or len(rows) > 20
    ):
        raise Phase8Error("native SemanticModel search response is malformed")
    result: set[str] = set()
    for row in rows:
        entity = row.get("entity") if isinstance(row, Mapping) else None
        urn = entity.get("urn") if isinstance(entity, Mapping) else None
        if (
            not isinstance(urn, str)
            or entity.get("type") != "SEMANTIC_MODEL"
            or urn in result
        ):
            raise Phase8Error("native SemanticModel search identity is malformed")
        result.add(urn)
    return result


async def _wait_model_search(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    present: bool,
    timeout_seconds: float,
) -> int:
    expected = semantic_model_urn(bundle)
    deadline = monotonic() + timeout_seconds
    while True:
        hit = expected in await _semantic_search(client, _MODEL_NAME)
        if hit is present:
            return int(hit)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise Phase8Error("native SemanticModel search state did not converge")
        await asyncio.sleep(min(1.0, remaining))


async def _relationship_probe(
    client: Any,
    *,
    actor_urn: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    grouped = relationship_capability_probe_aspects()
    audit = validated_audit_stamp(
        {"actor": actor_urn, "time": time_ns() // 1_000_000}
    )
    attempted: list[tuple[str, str]] = []
    try:
        for (entity_type, urn), aspects in grouped.items():
            attempted.append((entity_type, urn))
            await client.upsert_entity(entity_type, urn, aspects, audit)
        readback: list[dict[str, Any]] = []
        for (entity_type, urn), aspects in grouped.items():
            entity = await client.get_entity(urn, tuple(aspects))
            for name, expected in aspects.items():
                actual = aspect_value(entity, name)
                assert_contains(actual, expected, f"{urn}.{name}")
                readback.append(
                    {
                        "entity_type": entity_type,
                        "urn": urn,
                        "aspect_name": name,
                        "value": expected,
                    }
                )
        model = next(
            aspects for (entity_type, _urn), aspects in grouped.items()
            if entity_type == "semanticModel"
        )
        relationship = model["semanticModelInfo"]["relationships"]
        if relationship != [
            {
                "name": "probe_many_to_one",
                "from": "probe_left",
                "fromColumns": ["foreign_key"],
                "to": "probe_right",
                "toColumns": ["primary_key"],
                "cardinality": "N_ONE",
            }
        ]:
            raise Phase8Error("relationship/cardinality capability probe differs")
        return {
            "status": "RELATIONSHIP_CARDINALITY_READBACK_SUPPORTED",
            "entity_count": len(grouped),
            "relationship_count": 1,
            "cardinality": "N_ONE",
            "readback_sha256": canonical_sha256(
                sorted(readback, key=lambda item: (item["urn"], item["aspect_name"]))
            ),
        }
    finally:
        cleanup_error: BaseException | None = None
        for entity_type, urn in attempted:
            try:
                await client.upsert_entity(
                    entity_type,
                    urn,
                    {"status": {"removed": True}},
                    audit,
                )
            except BaseException as error:
                cleanup_error = cleanup_error or error
        if attempted and cleanup_error is None:
            await _wait_removed(
                client,
                attempted,
                removed=True,
                timeout_seconds=timeout_seconds,
            )
        if cleanup_error is not None:
            raise Phase8Error("relationship capability probe cleanup failed") from cleanup_error


async def _verify_phase3_metric_rollback(
    client: Any,
    bundle: Mapping[str, Any],
) -> int:
    expected: dict[str, Mapping[str, Any]] = {}
    for _entity_type, urn, name, value in iter_native_metric_aspects(bundle):
        if name == "metricInfo":
            expected[urn] = value
    for urn, metric_info in sorted(expected.items()):
        entity = await client.get_entity(urn, ("metricInfo", "structuredProperties"))
        assert_contains(aspect_value(entity, "metricInfo"), metric_info, f"{urn}.metricInfo")
        if "semanticModel" in aspect_value(entity, "metricInfo"):
            raise Phase8Error("Phase 8 MetricInfo survived rollback")
        if aspect_value(entity, "structuredProperties").get("properties") != []:
            raise Phase8Error("Phase 8 Metric assignment survived rollback")
    return len(expected)


async def _runtime_probe(
    *,
    label: str,
    candidate: ActiveRuntimeCatalogProjection,
    projection_repository: PostgresRuntimeCatalogProjectionRepository,
    runtime_catalog: RuntimeSearchOnlyCatalog,
    catalog: DataHubCatalogClient,
    trino: TrinoAsyncClient,
    model: ContractModelAdapter,
    manifest: ProductReleaseEvidenceManifest,
    database_url: str,
    sessionmaker: Any,
    timeout_seconds: float,
    node1_case: Mapping[str, Any],
    analysis_case: Mapping[str, Any],
    analysis_as_of: date,
    analysis_capability: Any,
    ordinal: int,
) -> dict[str, Any]:
    schema = TrinoSchemaInspector(trino, timeout_seconds=timeout_seconds)
    engine = QueryGovernanceEngine(
        runtime_catalog,
        schema,
        expected_context_release=candidate.projection.catalog_release_id,
        search_mode="datahub_lexical",
        projection_repository=StaticProjectionRepository(candidate),
        analysis_capability=analysis_capability,
    )
    try:
        readiness, receipt, latency = await _readiness(engine)
        if receipt != candidate.product_release_id:
            raise Phase8Error(f"{label} runtime readiness receipt differs")
        node_model = AuditedNode1Model(model, candidate)
        node_adapter = Node1CountingDataPlatform(engine)
        node_support = PipelineSupport(
            node_adapter,
            ContextPackageBuilder(),
            node_model,
        )
        node_result, node_state = await _evaluate_node1_case(
            node_adapter,
            node_support,
            candidate,
            node1_case,
            ordinal,
        )
        if node_state is None or node_result.get("exact") is not True:
            raise Phase8Error(f"{label} live Node1 exact-match failed")

        analysis_platform = AnalysisCountingDataPlatform(
            AcceptanceDataPlatform(
                engine,
                QueryExecutionService(
                    trino,
                    timeout_seconds=timeout_seconds,
                    state_ttl_seconds=300,
                    state_max_entries=20,
                ),
                catalog,
                trino,
            )
        )
        owner_id = uuid4()
        analysis_repository = PostgresAnalysisRepository(
            database_url,
            owner_id,
            session_factory=sessionmaker,
        )
        analysis_result = await _evaluate_analysis_case(
            platform=analysis_platform,
            model=ResultOnlyModel(),
            repository=analysis_repository,
            owner_id=owner_id,
            manifest=manifest,
            candidate=candidate,
            case=analysis_case,
            as_of=analysis_as_of,
            trace_prefix=f"phase8-{label.lower()}-{uuid4().hex[:10]}",
            trino=trino,
            timeout_seconds=timeout_seconds,
        )
        pointer = await projection_repository.load_active()
        return {
            "node1": {
                key: node_result[key]
                for key in (
                    "case_id",
                    "exact",
                    "selected_metric_ids",
                    "analysis_operation",
                    "dimension_ids",
                    "period_start",
                    "execution_asset_count",
                )
            },
            "analysis": {
                key: analysis_result[key]
                for key in (
                    "case_id",
                    "exact",
                    "operation",
                    "metric_ids",
                    "row_count",
                    "ast_sha256",
                    "result_sha256",
                )
            },
            "readiness": readiness,
            "readiness_latency_ms": latency,
            "node1_model_call_count": node_model.call_count,
            "node1_source_or_release_missing_count": (
                node_model.source_or_release_evidence_missing_count
            ),
            "sql_execution_count": analysis_platform.execute_count,
            "active_pointer_unchanged": (
                pointer.product_release_id != candidate.product_release_id
            ),
        }
    finally:
        await engine.aclose()


def _assert_runtime_nonregression(
    baseline: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    if (
        baseline["node1"] != after["node1"]
        or baseline["analysis"] != after["analysis"]
        or baseline["readiness"] != after["readiness"]
        or baseline["node1_model_call_count"] != 1
        or after["node1_model_call_count"] != 1
        or baseline["node1_source_or_release_missing_count"] != 0
        or after["node1_source_or_release_missing_count"] != 0
        or baseline["sql_execution_count"] != 1
        or after["sql_execution_count"] != 1
        or baseline["active_pointer_unchanged"] is not True
        or after["active_pointer_unchanged"] is not True
    ):
        raise Phase8Error("Search·Node1·SQL·result non-regression differs")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Phase 8 capability, equality, 비회귀, rollback과 release CAS를 순서대로 실행한다."""

    _validate_boundary(args)
    environment = _environment(args.env_file)
    node_gold = _node1_gold(NODE1_GOLD_FILE)
    analysis_gold = _analysis_gold(ANALYSIS_GOLD_FILE)
    sessionmaker = get_sessionmaker(args.database_url)
    projection_repository = PostgresRuntimeCatalogProjectionRepository(sessionmaker)
    previous_active = await projection_repository.load_active()
    if (
        previous_active.generation < 15
        or not previous_active.product_release_id.startswith(EXPECTED_PREVIOUS_PREFIX)
        or previous_active.projection.source_selection["authority_mode"]
        != "NATIVE_PRIORITY"
    ):
        raise Phase8Error("Phase 8 requires the verified Phase 7 active pointer")
    bundle = previous_active.projection.release.as_bundle()
    projection = native_semantic_shadow_projection(bundle)
    if projection["relationship_count"] != 0:
        raise Phase8Error("Phase 8 active release relationship inventory unexpectedly changed")
    previous_manifest = await _active_manifest(
        sessionmaker, previous_active.product_release_id
    )
    manifest = _phase8_manifest(previous_active, previous_manifest, projection)
    await _put_product_manifest(sessionmaker, manifest)
    candidate = await projection_repository.load_candidate(
        previous_active.projection.projection_id,
        manifest.product_release_id,
    )
    _capability_document, analysis_capability = _capability(
        CAPABILITY_FILE, candidate
    )

    ca_file = Path(environment["PHASE5_DATAHUB_CA_FILE"]).resolve(strict=True)
    account = token = token_id = None
    catalog: DataHubCatalogClient | None = None
    trino: TrinoAsyncClient | None = None
    model: ContractModelAdapter | None = None
    activated = False
    shadow_attempted = False
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
            try:
                model_probe = await probe_native_semantic_model(system)
                preflight = await _preflight_identities(system, bundle)
                relationship_probe = await _relationship_probe(
                    system,
                    actor_urn=actor_urn,
                    timeout_seconds=args.verify_timeout,
                )
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
                    raise Phase8Error(
                        f"target DataHub read identity failed: {error.category}"
                    ) from error
                if not healthy:
                    raise Phase8Error("temporary target DataHub identity is unhealthy")
                trino = TrinoAsyncClient(
                    args.trino_server,
                    environment["TRINO_DATAHUB_USER"],
                    environment["TRINO_DATAHUB_PASSWORD"],
                    ca_file=args.trino_ca_file,
                    request_timeout_seconds=args.timeout,
                )
                model = ContractModelAdapter.from_openai(
                    environment["OPENAI_ENDPOINT"],
                    token=environment["OPENAI_API_KEY"],
                    model=environment["OPENAI_MODEL"],
                    timeout_seconds=float(environment["MODEL_TIMEOUT_SECONDS"]),
                )
                runtime_catalog = RuntimeSearchOnlyCatalog(catalog)
                baseline = await _runtime_probe(
                    label="baseline",
                    candidate=candidate,
                    projection_repository=projection_repository,
                    runtime_catalog=runtime_catalog,
                    catalog=catalog,
                    trino=trino,
                    model=model,
                    manifest=manifest,
                    database_url=args.database_url,
                    sessionmaker=sessionmaker,
                    timeout_seconds=args.timeout,
                    node1_case=node_gold["cases"][0],
                    analysis_case=analysis_gold["cases"][0],
                    analysis_as_of=date.fromisoformat(str(analysis_gold["as_of"])),
                    analysis_capability=analysis_capability,
                    ordinal=800,
                )

                attempted_urns: list[str] = []
                shadow_attempted = True
                published = await publish_native_semantic_shadow(
                    system,
                    bundle,
                    actor_urn=actor_urn,
                    expected_projection_sha256=projection["projection_sha256"],
                    attempted_urns=attempted_urns,
                )
                verified = await verify_native_semantic_shadow(
                    system,
                    bundle,
                    expected_projection_sha256=projection["projection_sha256"],
                )
                published_search_hits = await _wait_model_search(
                    system,
                    bundle,
                    present=True,
                    timeout_seconds=args.verify_timeout,
                )
                after = await _runtime_probe(
                    label="after",
                    candidate=candidate,
                    projection_repository=projection_repository,
                    runtime_catalog=runtime_catalog,
                    catalog=catalog,
                    trino=trino,
                    model=model,
                    manifest=manifest,
                    database_url=args.database_url,
                    sessionmaker=sessionmaker,
                    timeout_seconds=args.timeout,
                    node1_case=node_gold["cases"][0],
                    analysis_case=analysis_gold["cases"][0],
                    analysis_as_of=date.fromisoformat(str(analysis_gold["as_of"])),
                    analysis_capability=analysis_capability,
                    ordinal=801,
                )
                _assert_runtime_nonregression(baseline, after)

                targets = native_semantic_status_targets(bundle)
                retired_count = await set_native_semantic_removed(
                    system,
                    bundle,
                    actor_urn=actor_urn,
                    removed=True,
                )
                restored_metric_count = await restore_phase3_metric_aspects(
                    system,
                    bundle,
                    actor_urn=actor_urn,
                )
                await _wait_removed(
                    system,
                    targets,
                    removed=True,
                    timeout_seconds=args.verify_timeout,
                )
                rollback_metric_count = await _verify_phase3_metric_rollback(
                    system, bundle
                )
                retired_search_hits = await _wait_model_search(
                    system,
                    bundle,
                    present=False,
                    timeout_seconds=args.verify_timeout,
                )

                await publish_native_semantic_shadow(
                    system,
                    bundle,
                    actor_urn=actor_urn,
                    expected_projection_sha256=projection["projection_sha256"],
                )
                final_verified = await verify_native_semantic_shadow(
                    system,
                    bundle,
                    expected_projection_sha256=projection["projection_sha256"],
                )
                await _wait_removed(
                    system,
                    targets,
                    removed=False,
                    timeout_seconds=args.verify_timeout,
                )
                restored_search_hits = await _wait_model_search(
                    system,
                    bundle,
                    present=True,
                    timeout_seconds=args.verify_timeout,
                )

                activated_pointer = await projection_repository.activate(
                    projection_id=candidate.projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=previous_active.generation,
                    action="ACTIVATE",
                    actor="phase8-acceptance",
                    reason="native semantic equality and runtime non-regression passed",
                )
                activated = True
                rolled_back = await projection_repository.activate(
                    projection_id=previous_active.projection.projection_id,
                    product_release_id=previous_active.product_release_id,
                    expected_generation=activated_pointer.generation,
                    action="ROLLBACK",
                    actor="phase8-acceptance",
                    reason="rehearse exact Phase 8 product rollback",
                )
                activated = False
                final_active = await projection_repository.activate(
                    projection_id=candidate.projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=rolled_back.generation,
                    action="ACTIVATE",
                    actor="phase8-acceptance",
                    reason="reactivate verified Phase 8 shadow release",
                )
                activated = True
                active_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    TrinoSchemaInspector(trino, timeout_seconds=args.timeout),
                    expected_context_release=candidate.projection.catalog_release_id,
                    search_mode="datahub_lexical",
                    projection_repository=projection_repository,
                    analysis_capability=analysis_capability,
                )
                try:
                    active_stages, active_receipt, active_latency = await _readiness(
                        active_engine
                    )
                finally:
                    await active_engine.aclose()
                if active_receipt != manifest.product_release_id:
                    raise Phase8Error("Phase 8 final active readiness differs")
                receipts = await _activation_receipts(
                    sessionmaker, manifest.product_release_id
                )
                tail = receipts[-3:]
                if [item["action"] for item in tail] != [
                    "ACTIVATE",
                    "ROLLBACK",
                    "ACTIVATE",
                ]:
                    raise Phase8Error("Phase 8 activation receipt sequence differs")
                verified_active = await projection_repository.load_active()
                if (
                    verified_active.product_release_id != manifest.product_release_id
                    or verified_active.generation != final_active.generation
                ):
                    raise Phase8Error("Phase 8 final active pointer differs")
                gate_complete = True
                return {
                    "status": "PHASE8_NATIVE_SEMANTIC_SHADOW_PASSED",
                    "target_project": args.target_project,
                    "database": DATABASE_NAME,
                    "datahub_model_version": model_probe["datahub_model_version"],
                    "previous_product_release_id": previous_active.product_release_id,
                    "product_release_id": manifest.product_release_id,
                    "final_generation": verified_active.generation,
                    "projection": projection,
                    "preflight": preflight,
                    "model_probe": model_probe,
                    "relationship_capability_probe": relationship_probe,
                    "published_entity_count": published["published_entity_count"],
                    "rest_aspect_equality": verified["rest_aspect_equality"],
                    "readback_projection_sha256": verified[
                        "readback_projection_sha256"
                    ],
                    "final_readback_projection_sha256": final_verified[
                        "readback_projection_sha256"
                    ],
                    "runtime_nonregression": {
                        "baseline": baseline,
                        "after": after,
                        "node1_equal": baseline["node1"] == after["node1"],
                        "sql_ast_equal": (
                            baseline["analysis"]["ast_sha256"]
                            == after["analysis"]["ast_sha256"]
                        ),
                        "result_equal": (
                            baseline["analysis"]["result_sha256"]
                            == after["analysis"]["result_sha256"]
                        ),
                    },
                    "rollback": {
                        "retired_entity_count": retired_count,
                        "restored_phase3_metric_count": restored_metric_count,
                        "rollback_metric_readback_count": rollback_metric_count,
                        "published_search_hit_count": published_search_hits,
                        "retired_search_hit_count": retired_search_hits,
                        "restored_search_hit_count": restored_search_hits,
                        "verified": True,
                    },
                    "active_readiness": {
                        "stages": active_stages,
                        "latency_ms": active_latency,
                    },
                    "activation_receipts": tail,
                    "runtime_authority_activated": False,
                    "active_release_relationship_count": 0,
                    "runtime_full_scroll_attempt_count": (
                        runtime_catalog.full_read_attempt_count
                    ),
                    "bounded_search_request_count": (
                        runtime_catalog.search_request_count
                    ),
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
                if shadow_attempted and not gate_complete:
                    try:
                        await set_native_semantic_removed(
                            system,
                            bundle,
                            actor_urn=actor_urn,
                            removed=True,
                        )
                        await restore_phase3_metric_aspects(
                            system,
                            bundle,
                            actor_urn=actor_urn,
                        )
                    except BaseException as error:
                        cleanup_errors.append(error)
                raise
            finally:
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
                if model is not None:
                    try:
                        await model.aclose()
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
            raise Phase8Error("Phase 8 temporary resource cleanup failed") from cleanup_errors[0]


def _run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(run(args))
    return asyncio.run(run(args))


def main(argv: list[str] | None = None) -> int:
    """성공 JSON 또는 secret 없는 typed 실패 JSON을 출력한다."""

    try:
        result = _run_acceptance(parse_args(argv))
    except (
        AcceptanceError,
        AdapterError,
        NativeSemanticShadowError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        output = {"status": "FAILED", "error_type": type(error).__name__}
        if isinstance(error, (AcceptanceError, NativeSemanticShadowError)):
            output["reason"] = str(error)
        print(json.dumps(output, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
