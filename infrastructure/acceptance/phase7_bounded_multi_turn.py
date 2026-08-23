"""Run the Phase 7 bounded multi-turn Gate in the approved isolated stack.

The runner uses the production Conversation orchestrator, PostgreSQL
repositories, DataHub lexical retrieval, the sealed analysis capability, the
configured Node 1/3 model endpoint, and read-only Trino.  It never mutates the
current ``answervice`` stack.  All App DB writes and runtime pointer rehearsals
are restricted to the isolated Phase 4 acceptance database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.analysis_repository import PostgresAnalysisRepository  # noqa: E402
from app.adapters.conversation_repository import ConversationRepository  # noqa: E402
from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.model_adapter import ContractModelAdapter  # noqa: E402
from app.adapters.query_execution import QueryExecutionService  # noqa: E402
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
from app.adapters.report_repository import PostgresReportRepository  # noqa: E402
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ActiveRuntimeCatalogProjection,
    PostgresRuntimeCatalogProjectionRepository,
    RuntimeCatalogRepositoryError,
)
from app.adapters.trino_async import AdapterError, TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import TrinoSchemaInspector  # noqa: E402
from app.capability_contracts import (  # noqa: E402
    CatalogReceipt,
    MigrationReceipt,
    ModelReceipt,
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
    ProductReleaseVector,
)
from app.contracts import RequestContext, Role, RouteType  # noqa: E402
from app.database import get_sessionmaker  # noqa: E402
from app.services.analysis.pipeline_support import PipelineSupport  # noqa: E402
from app.services.analysis.service import AnalysisService  # noqa: E402
from app.services.analysis.typed_sql_compiler import (  # noqa: E402
    TYPED_SQL_COMPILER_VERSION,
)
from app.services.context.builder import ContextPackageBuilder  # noqa: E402
from app.services.conversation.orchestrator import ConversationOrchestrator  # noqa: E402
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
from phase5_node1_grounding import (  # noqa: E402
    AuditedNode1Model,
    _active_manifest,
    _environment,
    _restore_previous,
)
from phase6_single_asset_analysis import (  # noqa: E402
    AcceptanceDataPlatform,
    CountingDataPlatform,
    _capability,
)
from src.ai.model_contracts import (  # noqa: E402
    model_release_checksum,
    model_release_manifest,
)
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


GOLD_FILE = (
    ROOT
    / "evals"
    / "golden_dialogue"
    / "answervice_ko_bounded_multiturn.v1.json"
)
CAPABILITY_FILE = (
    ROOT
    / "app"
    / "backend"
    / "contracts"
    / "analysis_capability.bounded_multi_turn.v1.json"
)
ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
EXPECTED_PREVIOUS_PREFIX = "ANSWERVICE-PHASE6-SINGLE-ASSET:"
EXPECTED_ASSET_FQN = "serving.analytics_v4_3.hotel_operations_daily"
MIGRATION_REVISION = "20260822_33"
EXPECTED_MODEL_RELEASE = "MODEL-RELEASE-v1.33.1"
EXPECTED_NODE1_PROMPT_RELEASE = "PROMPT-v1.26.1"
PERMISSION_LABEL = "phase7-isolated-admission"


class Phase7Error(AcceptanceError):
    """Phase 7 cannot be proved without lowering a transaction or lineage Gate."""


class AuditedConversationModel(AuditedNode1Model):
    """Audit Node 1 authority evidence and count every downstream model node."""

    def __init__(
        self,
        delegate: ContractModelAdapter,
        active: ActiveRuntimeCatalogProjection,
    ) -> None:
        super().__init__(delegate, active)
        self.generate_calls: list[str] = []
        self.node1_decisions: list[dict[str, object]] = []

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.generate_calls.append(node)
        return await self._delegate.generate(node, payload)

    async def normalize_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Retain only non-sensitive typed decision fields for Gate diagnosis."""

        result = await super().normalize_question(payload)
        self.node1_decisions.append(
            {
                "question": payload.get("question"),
                "metric_resolution": result.get("metric_resolution"),
                "selected_metric_count": len(
                    result.get("selected_metric_ids") or ()
                ),
                "measurement_count": len(
                    result.get("measurement_source_texts") or ()
                ),
                "requested_route": result.get("requested_route"),
                "is_elliptical": result.get("is_elliptical"),
                "period_count": len(result.get("period_candidates") or ()),
                "recheck_target": (
                    payload.get("interpretation_recheck", {}).get("target")
                    if isinstance(payload.get("interpretation_recheck"), dict)
                    else None
                ),
            }
        )
        return result


class UnavailablePinnedPlatform:
    """Inject an unavailable pinned product without changing the release tables."""

    def __init__(self, delegate: object, product_release_id: str) -> None:
        self._delegate = delegate
        self._product_release_id = product_release_id

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def get_product_release_readiness(
        self,
        product_release_id: str,
    ) -> tuple[dict[str, str], str | None, str | None]:
        if product_release_id == self._product_release_id:
            return (
                {"catalog": "not_ready", "semantic": "not_ready", "query": "not_ready"},
                None,
                None,
            )
        return await self._delegate.get_product_release_readiness(product_release_id)


class IncompatibleArtifactReadRepository:
    """Expose one deliberately incompatible read view without mutating the Artifact."""

    def __init__(self, delegate: ConversationRepository) -> None:
        self._delegate = delegate
        self._sessionmaker = delegate._sessionmaker

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def list_turns(self, conversation_id: UUID) -> list[dict[str, Any]]:
        turns = [dict(turn) for turn in await self._delegate.list_turns(conversation_id)]
        for turn in turns:
            if turn.get("route") == "ANALYSIS" and turn.get("artifact_id"):
                turn["data_snapshot_json"] = {
                    "columns": ["hotel", "room_revenue_krw"],
                    "rows": [{"hotel": "ACCEPTANCE", "room_revenue_krw": 1}],
                }
                turn["chart_spec_json"] = {
                    "chart_type": "bar",
                    "x_field": "hotel",
                    "y_fields": ["room_revenue_krw"],
                }
        return turns


class FaultAfterReportWrite:
    """Write through the caller transaction and then force its rollback."""

    def __init__(self, delegate: PostgresReportRepository) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def add_draft_in_session(self, session: object, draft: object) -> None:
        await self._delegate.add_draft_in_session(session, draft)
        raise RuntimeError("Phase 7 injected report terminal failure")

    async def replace_draft_blocks_in_session(
        self,
        session: object,
        definition_id: str,
        version: int,
        blocks: object,
    ) -> None:
        await self._delegate.replace_draft_blocks_in_session(
            session,
            definition_id,
            version,
            blocks,
        )
        raise RuntimeError("Phase 7 injected report terminal failure")


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
        raise Phase7Error("Phase 7 target project is outside the approved boundary")
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
            raise Phase7Error(f"{label} is outside the approved loopback boundary")
    database = make_url(args.database_url)
    if (
        database.drivername != "postgresql+psycopg"
        or database.host not in {"127.0.0.1", "localhost", "::1"}
        or database.port != DATABASE_PORT
        or database.database != DATABASE_NAME
        or database.username != "postgres"
        or database.password is not None
    ):
        raise Phase7Error("Phase 7 database is outside the isolated boundary")
    if args.timeout <= 0:
        raise Phase7Error("Phase 7 timeout must be positive")
    for supplied, expected, label in (
        (args.env_file, ENV_FILE, "environment"),
        (args.gold_file, GOLD_FILE, "Gold"),
        (args.capability_file, CAPABILITY_FILE, "capability"),
    ):
        try:
            resolved = supplied.resolve(strict=True)
        except OSError as error:
            raise Phase7Error(f"Phase 7 {label} file is unavailable") from error
        if resolved != expected.resolve(strict=True) or not resolved.is_file():
            raise Phase7Error(f"Phase 7 {label} file differs from the sealed path")
    try:
        ca_file = args.trino_ca_file.resolve(strict=True)
    except OSError as error:
        raise Phase7Error("Phase 7 Trino CA is unavailable") from error
    if not args.trino_ca_file.is_absolute() or not ca_file.is_file():
        raise Phase7Error("Phase 7 Trino CA is outside the explicit boundary")


def _gold(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Phase7Error("Phase 7 Gold cannot be read") from error
    if not isinstance(document, dict):
        raise Phase7Error("Phase 7 Gold must be an object")
    supplied = document.get("content_sha256")
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    thresholds = document.get("thresholds")
    dialogues = document.get("dialogues")
    if (
        supplied != canonical_sha256(payload)
        or document.get("schema_version")
        != "answervice.bounded_multi_turn_gold.v1"
        or document.get("status") != "SEALED"
        or not str(document.get("input_product_release_id", "")).startswith(
            EXPECTED_PREVIOUS_PREFIX
        )
        or document.get("scope", {}).get("asset_fqn") != EXPECTED_ASSET_FQN
        or not isinstance(thresholds, dict)
        or thresholds.get("min_dialogue_exact_match") != 1.0
        or any(
            value != 0 and value != 0.0
            for name, value in thresholds.items()
            if name != "min_dialogue_exact_match"
        )
        or not isinstance(dialogues, list)
        or [item.get("dialogue_id") for item in dialogues] != ["GD-01", "GD-02", "GD-03"]
    ):
        raise Phase7Error("Phase 7 Gold contract or thresholds differ")
    for dialogue in dialogues:
        turns = dialogue.get("turns")
        totals = dialogue.get("totals")
        if not isinstance(turns, list) or not turns or not isinstance(totals, dict):
            raise Phase7Error("Phase 7 dialogue shape differs")
        if [turn.get("turn") for turn in turns] != list(range(1, len(turns) + 1)):
            raise Phase7Error("Phase 7 Turn ordering differs")
        if any(len(turn.get("source_turns", [])) > 2 for turn in turns):
            raise Phase7Error("Phase 7 source Turn bound differs")
    current_anchor = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    if dialogues[-1].get("wall_clock_anchor") != current_anchor:
        raise Phase7Error("GD-03 sealed current-clock anchor is not today's Backend KST date")
    return document


def _phase7_manifest(
    active: ActiveRuntimeCatalogProjection,
    previous: ProductReleaseEvidenceManifest,
    gold: Mapping[str, object],
    capability_sha256: str,
) -> ProductReleaseEvidenceManifest:
    model_manifest = model_release_manifest()
    node1 = model_manifest.get("nodes", {}).get("node1", {})
    if (
        model_manifest.get("manifest_version") != EXPECTED_MODEL_RELEASE
        or node1.get("prompt_version") != EXPECTED_NODE1_PROMPT_RELEASE
    ):
        raise Phase7Error("Phase 7 model/prompt release differs")
    source, created_at = _source_receipt()
    projection = active.projection
    evidence = ProductReleaseEvidence(
        source=source,
        images=previous.evidence.images,
        migration=MigrationReceipt(
            revision=MIGRATION_REVISION,
            chain_sha256=_migration_chain_sha256(),
        ),
        model=ModelReceipt(
            release_id=EXPECTED_MODEL_RELEASE,
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
            prompt_release_id=EXPECTED_MODEL_RELEASE,
            policy_release_id=projection.release.policy_version,
            runtime_release_id="PHASE7-RUNTIME-v1:"
            + canonical_sha256(
                {
                    "projection_sha256": projection.projection_sha256,
                    "compiler": TYPED_SQL_COMPILER_VERSION,
                    "gold_sha256": gold["content_sha256"],
                    "analysis_capability_sha256": capability_sha256,
                    "conversation_schema_revision": MIGRATION_REVISION,
                }
            ),
        ),
    )
    identity = canonical_sha256(
        {
            "phase": "7",
            "contract": "bounded_multi_turn.v1",
            "gold_sha256": gold["content_sha256"],
            "analysis_capability_sha256": capability_sha256,
            "evidence": evidence.model_dump(mode="json"),
        }
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=f"ANSWERVICE-PHASE7-BOUNDED-MULTITURN:{identity}",
        evidence=evidence,
        created_at=created_at,
    )


async def _database_revision(sessionmaker: object) -> str:
    try:
        async with sessionmaker() as session:
            return str(
                (
                    await session.execute(
                        text("SELECT version_num FROM governance.alembic_version")
                    )
                ).scalar_one()
            )
    except SQLAlchemyError as error:
        raise Phase7Error("Phase 7 isolated migration revision is unreadable") from error


def _context(
    owner_id: UUID,
    active: ActiveRuntimeCatalogProjection,
    as_of: date,
    trace_prefix: str,
) -> RequestContext:
    return RequestContext(
        trace_id=f"{trace_prefix}-{uuid4().hex[:12]}",
        user_id=owner_id,
        role=Role.ANALYST,
        as_of=as_of,
        timezone="Asia/Seoul",
        permission_snapshot_id=PERMISSION_LABEL,
        product_release_id=active.product_release_id,
        semantic_release_id=active.projection.catalog_release_id,
    )


def _build_orchestrator(
    *,
    repository: ConversationRepository,
    platform: object,
    model: AuditedConversationModel,
    database_url: str,
    sessionmaker: object,
    report_wrapper: bool = False,
) -> ConversationOrchestrator:
    support = PipelineSupport(platform, ContextPackageBuilder(), model)

    async def submit_analysis(
        payload: object,
        context: RequestContext,
        execution_sink: object,
    ) -> object:
        return await AnalysisService(
            platform,
            model,
            context_builder=ContextPackageBuilder(),
            cache=IsolatedExecutionCache(),
        ).analyze(
            payload,
            context,
            RouteDecision(RouteType.GENERAL, None, True, True),
            execution_sink=execution_sink,
        )

    def report_factory(context: RequestContext, is_admin: bool) -> object:
        report = PostgresReportRepository(
            database_url,
            context.user_id,
            manage_all=is_admin,
            product_release_id=context.product_release_id,
            permission_snapshot_id=context.permission_snapshot_id,
            semantic_release_id=context.semantic_release_id,
            session_factory=sessionmaker,
        )
        return FaultAfterReportWrite(report) if report_wrapper else report

    return ConversationOrchestrator(
        repository=repository,
        data_platform=platform,
        support=support,
        submit_analysis=submit_analysis,
        report_repository_factory=report_factory,
        analysis_repository_factory=lambda owner_id: PostgresAnalysisRepository(
            database_url,
            owner_id,
            session_factory=sessionmaker,
        ),
    )


def _command_payload(
    dialogue_id: str,
    turn: Mapping[str, object],
    head_turn_id: UUID | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "user_message": str(turn["utterance"]),
        "idempotency_key": f"phase7-{dialogue_id.lower()}-{turn['turn']}-{uuid4().hex}",
        "expected_head_turn_id": str(head_turn_id) if head_turn_id else None,
        "requested_route": str(turn["route"]),
    }
    if turn.get("route") == "PRESENTATION":
        payload["presentation_type"] = str(turn["view"])
    return payload


async def _readback(
    sessionmaker: object,
    repository: ConversationRepository,
    conversation_id: UUID,
) -> dict[str, Any]:
    turns = await repository.list_turns(conversation_id)
    try:
        async with sessionmaker() as session:
            counts = dict(
                (
                    await session.execute(
                        text(
                            """
                            SELECT
                              (SELECT count(*) FROM chat.turns
                               WHERE conversation_id = :conversation_id) AS turns,
                              (SELECT count(*) FROM chat.analysis_requests
                               WHERE conversation_id = :conversation_id) AS runs,
                              (SELECT count(*) FROM query.query_executions q
                               JOIN chat.analysis_requests r USING (request_id)
                               WHERE r.conversation_id = :conversation_id) AS queries,
                              (SELECT count(*) FROM artifact.analysis_artifacts a
                               JOIN chat.analysis_requests r USING (request_id)
                               WHERE r.conversation_id = :conversation_id) AS artifacts,
                              (SELECT count(*) FROM artifact.view_specs v
                               WHERE v.artifact_id IN (
                                 SELECT artifact_id FROM chat.turns
                                 WHERE conversation_id = :conversation_id
                                   AND artifact_id IS NOT NULL
                               )) AS views,
                              (SELECT count(*) FROM report_v1.report_blocks b
                               WHERE b.definition_id IN (
                                 SELECT COALESCE(report_draft_definition_id, report_definition_id)
                                 FROM chat.turns
                                 WHERE conversation_id = :conversation_id
                               )) AS report_blocks
                            """
                        ),
                        {"conversation_id": conversation_id},
                    )
                ).mappings().one()
            )
            conversation = dict(
                (
                    await session.execute(
                        text(
                            """
                            SELECT head_turn_id, turn_count, wall_clock_anchor,
                                   data_focus_turn_id, data_focus_artifact_id,
                                   view_focus_turn_id, view_focus_spec_id,
                                   product_release_id, permission_snapshot_id,
                                   semantic_release_id
                            FROM chat.conversations
                            WHERE conversation_id = :conversation_id
                            """
                        ),
                        {"conversation_id": conversation_id},
                    )
                ).mappings().one()
            )
            report_blocks = [
                dict(row)
                for row in (
                    await session.execute(
                        text(
                            """
                            SELECT b.definition_id, b.block_id, b.block_type,
                                   b.artifact_id, b.view_spec_id, b.y
                            FROM report_v1.report_blocks b
                            WHERE b.definition_id IN (
                              SELECT COALESCE(report_draft_definition_id, report_definition_id)
                              FROM chat.turns
                              WHERE conversation_id = :conversation_id
                            )
                            ORDER BY b.y, b.block_id
                            """
                        ),
                        {"conversation_id": conversation_id},
                    )
                ).mappings().all()
            ]
    except SQLAlchemyError as error:
        raise Phase7Error("Phase 7 PostgreSQL read-back failed") from error
    return {
        "turns": turns,
        "counts": {name: int(value) for name, value in counts.items()},
        "conversation": conversation,
        "report_blocks": report_blocks,
    }


def _stored_period(
    slots: Mapping[str, object],
    slot_name: str,
    *,
    allow_blocked_candidate: bool,
) -> dict[str, str] | None:
    """Return one persisted half-open period in canonical date form.

    Successful Turns persist resolver output under ``time_range``.  A typed
    ``OUT_OF_DATA_RANGE`` Turn stops in preflight and therefore persists the
    single validated Node 1 period under ``period_candidates`` instead.  The
    fallback is deliberately unavailable for successful, ambiguous, or
    comparison Turns so the acceptance assertion cannot waive a missing
    resolver slot.
    """

    raw_period = slots.get(slot_name)
    if not isinstance(raw_period, Mapping):
        candidates = slots.get("period_candidates")
        if (
            not allow_blocked_candidate
            or slot_name != "time_range"
            or slots.get("period_relationship") != "single"
            or not isinstance(candidates, list)
            or len(candidates) != 1
            or not isinstance(candidates[0], Mapping)
        ):
            return None
        raw_period = candidates[0]

    def canonical_date(value: object) -> str | None:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value).date().isoformat()
        except ValueError:
            return None

    start = canonical_date(raw_period.get("start"))
    end_exclusive = canonical_date(raw_period.get("end_exclusive"))
    if start is None or end_exclusive is None or start >= end_exclusive:
        return None
    return {"start": start, "end_exclusive": end_exclusive}


def _assert_dialogue(
    dialogue: Mapping[str, object],
    readback: Mapping[str, object],
    product_release_id: str,
) -> None:
    turns = list(readback["turns"])
    expected_turns = list(dialogue["turns"])
    if len(turns) != len(expected_turns):
        raise Phase7Error(f"{dialogue['dialogue_id']} Turn count differs")
    for index, (expected, actual) in enumerate(
        zip(expected_turns, turns, strict=True)
    ):
        expected_status = str(expected["terminal_status"])
        expected_sources = [
            str(turns[int(ordinal) - 1]["turn_id"])
            for ordinal in expected.get("source_turns", [])
        ]
        slots = actual.get("resolved_slots") or {}
        if (
            actual.get("turn_index") != index
            or actual.get("user_message") != expected.get("utterance")
            or actual.get("route") != expected.get("route")
            or actual.get("terminal_status") != expected_status
            or list(map(str, actual.get("source_turn_ids") or [])) != expected_sources
            or actual.get("product_release_id") != product_release_id
            or len(actual.get("source_turn_ids") or []) > 2
            or (
                index == 0
                and actual.get("reply_to_turn_id") is not None
            )
            or (
                index > 0
                and str(actual.get("reply_to_turn_id"))
                != str(turns[index - 1]["turn_id"])
            )
        ):
            raise Phase7Error(
                f"{dialogue['dialogue_id']} Turn {index + 1} lineage differs"
            )
        if expected.get("reason_code") and actual.get("reason_code") != expected.get(
            "reason_code"
        ):
            raise Phase7Error(
                f"{dialogue['dialogue_id']} Turn {index + 1} reason differs"
            )
        if expected.get("analysis_operation") and slots.get(
            "analysis_operation"
        ) != expected.get("analysis_operation"):
            raise Phase7Error(
                f"{dialogue['dialogue_id']} Turn {index + 1} operation differs: "
                f"{slots.get('analysis_operation')}"
            )
        for slot_name, expected_name in (
            ("time_range", "period"),
            ("comparison_time_range", "comparison_period"),
        ):
            expected_period = expected.get(expected_name)
            actual_period = _stored_period(
                slots,
                slot_name,
                allow_blocked_candidate=(
                    actual.get("terminal_status") == "BLOCKED"
                    and actual.get("reason_code") == "OUT_OF_DATA_RANGE"
                ),
            )
            if expected_period and actual_period != {
                "start": expected_period.get("start"),
                "end_exclusive": expected_period.get("end_exclusive"),
            }:
                raise Phase7Error(
                    f"{dialogue['dialogue_id']} Turn {index + 1} period differs: "
                    f"actual={canonical_json(actual_period)}"
                )
        if expected.get("route") == "PRESENTATION" and actual.get(
            "view_type"
        ) != expected.get("view"):
            raise Phase7Error(
                f"{dialogue['dialogue_id']} Turn {index + 1} View differs"
            )
    if readback["counts"] != dialogue["totals"]:
        raise Phase7Error(
            f"{dialogue['dialogue_id']} persistence cardinality differs: "
            + canonical_json(readback["counts"])
        )
    conversation = readback["conversation"]
    if (
        conversation["turn_count"] != len(turns)
        or str(conversation["head_turn_id"]) != str(turns[-1]["turn_id"])
        or conversation["wall_clock_anchor"].isoformat()
        != dialogue["wall_clock_anchor"]
        or conversation["product_release_id"] != product_release_id
    ):
        raise Phase7Error(f"{dialogue['dialogue_id']} Conversation state differs")

    if dialogue["dialogue_id"] == "GD-01":
        if (
            conversation["data_focus_turn_id"] != turns[-1]["turn_id"]
            or conversation["view_focus_turn_id"] != turns[-1]["turn_id"]
        ):
            raise Phase7Error("GD-01 final focus differs")
    elif dialogue["dialogue_id"] == "GD-02":
        artifact_ids = {str(turn["artifact_id"]) for turn in turns if turn.get("artifact_id")}
        presentation_views = [turn.get("view_type") for turn in turns[1:4]]
        first_snapshot = turns[0].get("data_snapshot_json") or {}
        first_chart = turns[0].get("chart_spec_json") or {}
        expected_report_views = [turns[2]["view_spec_id"], turns[3]["view_spec_id"]]
        report_blocks = list(readback["report_blocks"])
        if (
            len(artifact_ids) != 1
            or presentation_views != ["LINE", "BAR", "TABLE"]
            or "period" not in (first_snapshot.get("columns") or [])
            or first_chart.get("x_field") != "period"
            or [block["block_type"] for block in report_blocks]
            != ["chart", "table"]
            or [block["view_spec_id"] for block in report_blocks]
            != expected_report_views
            or conversation["data_focus_turn_id"] != turns[0]["turn_id"]
            or conversation["view_focus_turn_id"] != turns[3]["turn_id"]
        ):
            raise Phase7Error("GD-02 Artifact/View/Report lineage differs")
    else:
        if (
            turns[0]["request_id"] is not None
            or turns[0]["artifact_id"] is not None
            or turns[0]["view_spec_id"] is not None
            or turns[1]["source_turn_ids"]
            or turns[1]["clarifies_turn_id"] != turns[0]["turn_id"]
            or conversation["data_focus_turn_id"] != turns[1]["turn_id"]
        ):
            raise Phase7Error("GD-03 blocked/resume lineage differs")


async def _execute_dialogue(
    *,
    dialogue: Mapping[str, object],
    orchestrator: ConversationOrchestrator,
    repository: ConversationRepository,
    sessionmaker: object,
    owner_id: UUID,
    candidate: ActiveRuntimeCatalogProjection,
    trace_prefix: str,
) -> dict[str, Any]:
    anchor = date.fromisoformat(str(dialogue["wall_clock_anchor"]))
    conversation = await orchestrator.create_conversation(
        _context(owner_id, candidate, anchor, trace_prefix),
        str(dialogue["dialogue_id"]),
    )
    conversation_id = UUID(str(conversation["conversation_id"]))
    head: UUID | None = None
    command_payloads: list[dict[str, object]] = []
    for ordinal, expected in enumerate(dialogue["turns"], start=1):
        payload = _command_payload(str(dialogue["dialogue_id"]), expected, head)
        command_payloads.append(payload)
        result = await orchestrator.execute_command(
            conversation_id,
            payload,
            _context(owner_id, candidate, anchor, trace_prefix),
        )
        expected_result_status = (
            "SUCCESS"
            if expected["terminal_status"] == "SUCCEEDED"
            else expected["terminal_status"]
        )
        if result.get("status") != expected_result_status:
            raise Phase7Error(
                f"{dialogue['dialogue_id']} Turn {ordinal} failed: "
                f"status={result.get('status')}; code={result.get('code')}"
            )
        head = UUID(str(result["turn"]["turn_id"]))
        if dialogue["dialogue_id"] == "GD-03" and ordinal == 1:
            blocked = await _readback(sessionmaker, repository, conversation_id)
            if blocked["counts"] != dialogue["initial_blocked_totals"]:
                raise Phase7Error("GD-03 initial no-Run cardinality differs")
    readback = await _readback(sessionmaker, repository, conversation_id)
    _assert_dialogue(dialogue, readback, candidate.product_release_id)
    return {
        "dialogue_id": dialogue["dialogue_id"],
        "conversation_id": str(conversation_id),
        "exact": True,
        "counts": readback["counts"],
        "turn_ids": [str(turn["turn_id"]) for turn in readback["turns"]],
        "artifact_ids": [
            str(turn["artifact_id"])
            for turn in readback["turns"]
            if turn.get("artifact_id")
        ],
        "command_payloads": command_payloads,
        "readback": readback,
    }


async def _core_negative_gates(
    *,
    evaluation: dict[str, Any],
    orchestrator: ConversationOrchestrator,
    repository: ConversationRepository,
    platform: CountingDataPlatform,
    model: AuditedConversationModel,
    sessionmaker: object,
    database_url: str,
    owner_id: UUID,
    candidate: ActiveRuntimeCatalogProjection,
    trace_prefix: str,
) -> dict[str, int]:
    conversation_id = UUID(evaluation["conversation_id"])
    first_payload = dict(evaluation["command_payloads"][0])
    before = await _readback(sessionmaker, repository, conversation_id)
    before_executes = platform.execute_count

    # A fresh repository instance simulates refresh/retry hydration.
    refreshed = _build_orchestrator(
        repository=ConversationRepository(sessionmaker),
        platform=platform,
        model=model,
        database_url=database_url,
        sessionmaker=sessionmaker,
    )
    replay = await refreshed.execute_command(
        conversation_id,
        first_payload,
        _context(
            owner_id,
            candidate,
            date.fromisoformat("2025-09-02"),
            trace_prefix,
        ),
    )
    mismatch_payload = {**first_payload, "user_message": "다른 authoritative payload"}
    mismatch = await refreshed.execute_command(
        conversation_id,
        mismatch_payload,
        _context(
            owner_id,
            candidate,
            date.fromisoformat("2025-09-02"),
            trace_prefix,
        ),
    )
    stale = await refreshed.execute_command(
        conversation_id,
        {
            "user_message": "2025년 8월 인식 객실 매출을 다시 보여줘.",
            "idempotency_key": f"phase7-stale-{uuid4().hex}",
            "expected_head_turn_id": str(uuid4()),
            "requested_route": "ANALYSIS",
        },
        _context(
            owner_id,
            candidate,
            date.fromisoformat("2025-09-02"),
            trace_prefix,
        ),
    )
    changed_role = _context(
        owner_id,
        candidate,
        date.fromisoformat("2025-09-02"),
        trace_prefix,
    ).model_copy(update={"role": Role.REPORT_ADMIN})
    permission = await refreshed.execute_command(
        conversation_id,
        {
            "user_message": "2025년 8월 인식 객실 매출을 다시 보여줘.",
            "idempotency_key": f"phase7-permission-{uuid4().hex}",
            "expected_head_turn_id": str(before["conversation"]["head_turn_id"]),
            "requested_route": "ANALYSIS",
        },
        changed_role,
    )
    unavailable_platform = UnavailablePinnedPlatform(
        platform,
        candidate.product_release_id,
    )
    unavailable = _build_orchestrator(
        repository=repository,
        platform=unavailable_platform,
        model=model,
        database_url=database_url,
        sessionmaker=sessionmaker,
    )
    retired = await unavailable.execute_command(
        conversation_id,
        {
            "user_message": "2025년 8월 인식 객실 매출을 다시 보여줘.",
            "idempotency_key": f"phase7-retired-{uuid4().hex}",
            "expected_head_turn_id": str(before["conversation"]["head_turn_id"]),
            "requested_route": "ANALYSIS",
        },
        _context(
            owner_id,
            candidate,
            date.fromisoformat("2025-09-02"),
            trace_prefix,
        ),
    )
    after = await _readback(sessionmaker, repository, conversation_id)
    if (
        replay.get("is_idempotent_replay") is not True
        or mismatch.get("code") != "IDEMPOTENCY_CONFLICT"
        or stale.get("code") != "CONVERSATION_CONFLICT"
        or permission.get("code") != "ACCESS_DENIED"
        or retired.get("code") != "RESOURCE_CONFLICT"
        or after["counts"] != before["counts"]
        or platform.execute_count != before_executes
    ):
        raise Phase7Error("Phase 7 replay/CAS/permission/release negative differs")
    return {
        "idempotent_replay_count": 1,
        "idempotency_mismatch_block_count": 1,
        "stale_head_block_count": 1,
        "permission_change_block_count": 1,
        "unavailable_pinned_release_block_count": 1,
        "duplicate_mutation_count": 0,
    }


async def _view_and_report_negative_gates(
    *,
    evaluation: dict[str, Any],
    repository: ConversationRepository,
    platform: CountingDataPlatform,
    model: AuditedConversationModel,
    sessionmaker: object,
    database_url: str,
    owner_id: UUID,
    candidate: ActiveRuntimeCatalogProjection,
    trace_prefix: str,
) -> dict[str, int]:
    """Prove typed View blocking and Report rollback without another query."""

    conversation_id = UUID(evaluation["conversation_id"])
    before_view = await _readback(sessionmaker, repository, conversation_id)
    before_executes = platform.execute_count
    before_model_calls = model.call_count
    incompatible_repository = IncompatibleArtifactReadRepository(repository)
    incompatible = _build_orchestrator(
        repository=incompatible_repository,
        platform=platform,
        model=model,
        database_url=database_url,
        sessionmaker=sessionmaker,
    )
    blocked_view = await incompatible.execute_command(
        conversation_id,
        {
            "user_message": "시간축이 없는 결과를 선 그래프로 전환해줘.",
            "idempotency_key": f"phase7-view-schema-{uuid4().hex}",
            "expected_head_turn_id": str(
                before_view["conversation"]["head_turn_id"]
            ),
            "requested_route": "PRESENTATION",
            "presentation_type": "LINE",
        },
        _context(
            owner_id,
            candidate,
            date.fromisoformat("2025-09-02"),
            trace_prefix,
        ),
    )
    after_view = await _readback(sessionmaker, repository, conversation_id)
    expected_counts = {
        **before_view["counts"],
        "turns": before_view["counts"]["turns"] + 1,
    }
    if (
        blocked_view.get("status") != "BLOCKED"
        or blocked_view.get("code") != "RESULT_VALIDATION_FAILED"
        or blocked_view["turn"].get("view_spec_id") is not None
        or blocked_view["turn"].get("terminal_status") != "BLOCKED"
        or after_view["counts"] != expected_counts
        or after_view["conversation"]["data_focus_turn_id"]
        != before_view["conversation"]["data_focus_turn_id"]
        or after_view["conversation"]["view_focus_turn_id"]
        != before_view["conversation"]["view_focus_turn_id"]
        or platform.execute_count != before_executes
        or model.call_count != before_model_calls
    ):
        raise Phase7Error("Phase 7 incompatible View zero-query block differs")

    before_report = after_view
    report_payload = {
        "user_message": "현재 그래프와 표를 보고서에 다시 담아줘.",
        "idempotency_key": f"phase7-report-fault-{uuid4().hex}",
        "expected_head_turn_id": str(
            before_report["conversation"]["head_turn_id"]
        ),
        "requested_route": "REPORT_ACTION",
    }
    faulting = _build_orchestrator(
        repository=repository,
        platform=platform,
        model=model,
        database_url=database_url,
        sessionmaker=sessionmaker,
        report_wrapper=True,
    )
    try:
        await faulting.execute_command(
            conversation_id,
            report_payload,
            _context(
                owner_id,
                candidate,
                date.fromisoformat("2025-09-02"),
                trace_prefix,
            ),
        )
    except RuntimeError as error:
        if "Phase 7 injected report terminal failure" not in str(error):
            raise Phase7Error("Phase 7 Report fault type differs") from error
    else:
        raise Phase7Error("Phase 7 Report fault injection did not fail")

    replay = await faulting.execute_command(
        conversation_id,
        report_payload,
        _context(
            owner_id,
            candidate,
            date.fromisoformat("2025-09-02"),
            trace_prefix,
        ),
    )
    failed_command = await repository.get_command(
        conversation_id,
        str(report_payload["idempotency_key"]),
    )
    after_report = await _readback(sessionmaker, repository, conversation_id)
    if (
        replay.get("status") != "FAILED"
        or replay.get("is_idempotent_replay") is not True
        or failed_command is None
        or failed_command.get("status") != "FAILED"
        or failed_command.get("turn_id") is not None
        or after_report["counts"] != before_report["counts"]
        or after_report["conversation"] != before_report["conversation"]
        or after_report["report_blocks"] != before_report["report_blocks"]
        or platform.execute_count != before_executes
        or model.call_count != before_model_calls
    ):
        raise Phase7Error("Phase 7 Report atomic rollback/retry differs")
    return {
        "incompatible_view_block_count": 1,
        "incompatible_view_query_count": 0,
        "report_fault_rollback_count": 1,
        "report_fault_retry_replay_count": 1,
        "report_fault_query_count": 0,
    }


async def _activation_receipts(
    sessionmaker: object,
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
    sessionmaker = get_sessionmaker(args.database_url)
    if await _database_revision(sessionmaker) != MIGRATION_REVISION:
        raise Phase7Error("Phase 7 isolated DB is not at the sealed migration head")
    projection_repository = PostgresRuntimeCatalogProjectionRepository(sessionmaker)
    previous_active = await projection_repository.load_active()
    if (
        previous_active.product_release_id != gold["input_product_release_id"]
        or not previous_active.product_release_id.startswith(EXPECTED_PREVIOUS_PREFIX)
    ):
        raise Phase7Error("Phase 7 requires the exact sealed Phase 6 active pointer")
    previous_manifest = await _active_manifest(
        sessionmaker,
        previous_active.product_release_id,
    )
    capability_document, analysis_capability = _capability(
        args.capability_file,
        previous_active,
    )
    asset_capability = analysis_capability.assets[0]
    if (
        asset_capability.asset_fqn != EXPECTED_ASSET_FQN
        or asset_capability.data_available_from != date(2025, 7, 1)
        or asset_capability.data_available_through != date(2025, 8, 31)
        or asset_capability.conversation_default_operation != "time_trend"
    ):
        raise Phase7Error("Phase 7 release-bound data availability differs")
    manifest = _phase7_manifest(
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

    ca_file = Path(environment["PHASE5_DATAHUB_CA_FILE"]).resolve(strict=True)
    account = token = token_id = None
    catalog: DataHubCatalogClient | None = None
    trino: TrinoAsyncClient | None = None
    model: ContractModelAdapter | None = None
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
                    raise Phase7Error(
                        f"target DataHub read identity failed: {error.category}"
                    ) from error
                if not healthy:
                    raise Phase7Error("temporary target DataHub identity is unhealthy")
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
                    raise Phase7Error("Phase 7 candidate readiness receipt differs")
                pointer_after_canary = await projection_repository.load_active()
                if (
                    pointer_after_canary.product_release_id
                    != previous_active.product_release_id
                    or pointer_after_canary.generation != previous_active.generation
                ):
                    raise Phase7Error("Phase 7 canary changed the active pointer")

                model = ContractModelAdapter.from_openai(
                    environment["OPENAI_ENDPOINT"],
                    token=environment["OPENAI_API_KEY"],
                    model=environment["OPENAI_MODEL"],
                    timeout_seconds=float(environment["MODEL_TIMEOUT_SECONDS"]),
                )
                audited_model = AuditedConversationModel(model, candidate)
                platform = CountingDataPlatform(
                    AcceptanceDataPlatform(
                        candidate_engine,
                        QueryExecutionService(
                            trino,
                            timeout_seconds=args.timeout,
                            state_ttl_seconds=300,
                            state_max_entries=200,
                        ),
                        catalog,
                        trino,
                    )
                )
                repository = ConversationRepository(sessionmaker)
                orchestrator = _build_orchestrator(
                    repository=repository,
                    platform=platform,
                    model=audited_model,
                    database_url=args.database_url,
                    sessionmaker=sessionmaker,
                )
                owner_id = uuid4()
                trace_prefix = f"phase7-{uuid4().hex[:12]}"
                # Range-block resume is the most model-sensitive scenario. Run it
                # first so a typed failure stops before unrelated paid calls, then
                # restore the sealed Gold ordering in the evidence payload.
                dialogue_by_id = {
                    str(item["dialogue_id"]): item for item in gold["dialogues"]
                }
                evaluated_by_id: dict[str, dict[str, Any]] = {}
                for dialogue_id in ("GD-03", "GD-01", "GD-02"):
                    dialogue = dialogue_by_id[dialogue_id]
                    try:
                        evaluated_by_id[dialogue_id] = await _execute_dialogue(
                            dialogue=dialogue,
                            orchestrator=orchestrator,
                            repository=repository,
                            sessionmaker=sessionmaker,
                            owner_id=owner_id,
                            candidate=candidate,
                            trace_prefix=trace_prefix,
                        )
                    except Phase7Error as error:
                        raise Phase7Error(
                            f"{error}; node1_tail="
                            f"{canonical_json(audited_model.node1_decisions[-4:])}"
                        ) from error
                evaluations = [
                    evaluated_by_id[str(item["dialogue_id"])]
                    for item in gold["dialogues"]
                ]
                if any(item["exact"] is not True for item in evaluations):
                    raise Phase7Error("Phase 7 Golden Dialogue exact-match failed")
                negatives = await _core_negative_gates(
                    evaluation=evaluations[0],
                    orchestrator=orchestrator,
                    repository=repository,
                    platform=platform,
                    model=audited_model,
                    sessionmaker=sessionmaker,
                    database_url=args.database_url,
                    owner_id=owner_id,
                    candidate=candidate,
                    trace_prefix=trace_prefix,
                )
                negatives.update(
                    await _view_and_report_negative_gates(
                        evaluation=evaluations[1],
                        repository=repository,
                        platform=platform,
                        model=audited_model,
                        sessionmaker=sessionmaker,
                        database_url=args.database_url,
                        owner_id=owner_id,
                        candidate=candidate,
                        trace_prefix=trace_prefix,
                    )
                )
                if any(
                    audited_model.generate_calls.count(name)
                    for name in ("node2", "node2_repair")
                ):
                    raise Phase7Error("Phase 7 deterministic path called Node 2")

                activated_pointer = await projection_repository.activate(
                    projection_id=candidate.projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=previous_active.generation,
                    action="ACTIVATE",
                    actor="phase7-acceptance",
                    reason="bounded multi-turn exact transaction Gate passed",
                )
                activated = True
                pinned_conversation = await orchestrator.create_conversation(
                    _context(
                        owner_id,
                        candidate,
                        date.fromisoformat("2025-09-02"),
                        trace_prefix,
                    ),
                    "Phase 7 pinned release continuity",
                )
                rolled_back = await projection_repository.activate(
                    projection_id=previous_active.projection.projection_id,
                    product_release_id=previous_active.product_release_id,
                    expected_generation=activated_pointer.generation,
                    action="ROLLBACK",
                    actor="phase7-acceptance",
                    reason="verify pinned Conversation across active rollback",
                )
                activated = False
                active_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    schema,
                    expected_context_release=candidate.projection.catalog_release_id,
                    search_mode="datahub_lexical",
                    projection_repository=projection_repository,
                    analysis_capability=analysis_capability,
                )
                engines.append(active_engine)
                pinned_platform = CountingDataPlatform(
                    AcceptanceDataPlatform(
                        active_engine,
                        QueryExecutionService(trino, timeout_seconds=args.timeout),
                        catalog,
                        trino,
                    )
                )
                pinned_orchestrator = _build_orchestrator(
                    repository=repository,
                    platform=pinned_platform,
                    model=audited_model,
                    database_url=args.database_url,
                    sessionmaker=sessionmaker,
                )
                # Release continuity is the variable under test. Reuse the sealed
                # GD-01 analysis utterance that already passed exact-match above;
                # adding an unsealed modifier such as "다시" introduces an
                # unrelated Node 1 intent-classification variable into this Gate.
                pinned_probe_question = str(
                    dialogue_by_id["GD-01"]["turns"][0]["utterance"]
                )
                pinned_result = await pinned_orchestrator.execute_command(
                    UUID(str(pinned_conversation["conversation_id"])),
                    {
                        "user_message": pinned_probe_question,
                        "idempotency_key": f"phase7-pinned-{uuid4().hex}",
                        "expected_head_turn_id": None,
                        "requested_route": "ANALYSIS",
                    },
                    _context(
                        owner_id,
                        candidate,
                        date.fromisoformat("2025-09-02"),
                        trace_prefix,
                    ),
                )
                if (
                    pinned_result.get("status") != "SUCCESS"
                    or pinned_result["turn"]["product_release_id"]
                    != manifest.product_release_id
                    or pinned_platform.execute_count != 1
                ):
                    raise Phase7Error(
                        "pinned release did not continue across rollback: "
                        f"status={pinned_result.get('status')}; "
                        f"code={pinned_result.get('code')}; "
                        f"node1_tail={canonical_json(audited_model.node1_decisions[-1:])}"
                    )
                final_active = await projection_repository.activate(
                    projection_id=candidate.projection.projection_id,
                    product_release_id=manifest.product_release_id,
                    expected_generation=rolled_back.generation,
                    action="ACTIVATE",
                    actor="phase7-acceptance",
                    reason="reactivate verified bounded multi-turn release",
                )
                activated = True
                active_readiness, active_receipt, active_latency = await _readiness(
                    active_engine
                )
                if active_receipt != manifest.product_release_id:
                    raise Phase7Error("Phase 7 final active readiness differs")
                receipts = await _activation_receipts(
                    sessionmaker,
                    manifest.product_release_id,
                )
                tail = receipts[-3:]
                if [item["action"] for item in tail] != [
                    "ACTIVATE",
                    "ROLLBACK",
                    "ACTIVATE",
                ]:
                    raise Phase7Error("Phase 7 activation receipt sequence differs")
                verified_active = await projection_repository.load_active()
                if (
                    verified_active.product_release_id != manifest.product_release_id
                    or verified_active.generation != final_active.generation
                ):
                    raise Phase7Error("Phase 7 final pointer differs")
                return {
                    "status": "PHASE7_BOUNDED_MULTI_TURN_PASSED",
                    "target_project": args.target_project,
                    "database": DATABASE_NAME,
                    "migration_revision": MIGRATION_REVISION,
                    "gold_dataset_id": gold["dataset_id"],
                    "gold_content_sha256": gold["content_sha256"],
                    "analysis_capability_sha256": capability_document[
                        "content_sha256"
                    ],
                    "dialogue_count": len(evaluations),
                    "dialogue_exact_count": len(evaluations),
                    "dialogue_exact_rate": 1.0,
                    "evaluations": [
                        {
                            key: value
                            for key, value in item.items()
                            if key not in {"readback", "command_payloads"}
                        }
                        for item in evaluations
                    ],
                    "candidate_execution_count": platform.execute_count,
                    "node1_model_call_count": audited_model.call_count,
                    "node1_period_recheck_call_count": sum(
                        item.get("recheck_target") == "period_candidates"
                        for item in audited_model.node1_decisions
                    ),
                    "node2_model_call_count": sum(
                        audited_model.generate_calls.count(name)
                        for name in ("node2", "node2_repair")
                    ),
                    "node3_model_call_count": audited_model.generate_calls.count(
                        "node3"
                    ),
                    "source_or_release_evidence_missing_count": (
                        audited_model.source_or_release_evidence_missing_count
                    ),
                    "negative_gates": {
                        **negatives,
                        "pinned_release_continuation_count": 1,
                        "pinned_release_rebinding_count": 0,
                    },
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
                    "runtime_full_scroll_attempt_count": (
                        runtime_catalog.full_read_attempt_count
                    ),
                    "bounded_search_request_count": runtime_catalog.search_request_count,
                    "temporary_read_token_revoked": True,
                    "temporary_service_account_deleted": True,
                }
            except BaseException:
                if activated:
                    try:
                        await _restore_previous(
                            projection_repository,
                            previous_active,
                        )
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
                if model is not None:
                    try:
                        await model.aclose()
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
            raise Phase7Error("Phase 7 temporary resource cleanup failed") from cleanup_errors[0]


def _run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
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
            output["reason"] = " ".join(str(error).split())[:1000]
        print(json.dumps(output, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
