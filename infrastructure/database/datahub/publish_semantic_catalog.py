"""서명된 live authoring 검증 뒤에만 사용하는 내부 semantic catalog publisher다."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from http_client import DataHubMetadataAdminClient  # noqa: E402
from metadata_aspects import aspect_counts, iter_aspects  # noqa: E402
from metadata_contract import validate_bundle  # noqa: E402
from metadata_rest import preflight_owner_entities  # noqa: E402
from metadata_wire import validated_audit_stamp  # noqa: E402
from src.data.governance_contract import catalog_hash  # noqa: E402


def _epoch_ms() -> int:
    return time.time_ns() // 1_000_000


async def publish_bundle(
    server: str,
    bundle: dict[str, object],
    *,
    actor_urn: str,
    token: str | None = None,
    ca_file: str | Path | None = None,
    timeout: float = 30.0,
    http: httpx.AsyncClient | None = None,
    clock: Callable[[], int] = _epoch_ms,
) -> dict[str, object]:
    """로컬 JSON 파일을 만들지 않고 메모리의 검증된 bundle을 직접 발행한다."""

    validate_bundle(bundle)
    audit_stamp = validated_audit_stamp({"actor": actor_urn, "time": clock()})
    async with DataHubMetadataAdminClient(
        server,
        token=token,
        ca_file=ca_file,
        timeout_seconds=timeout,
        http=http,
    ) as client:
        await preflight_owner_entities(client, bundle)
        grouped: dict[tuple[str, str], dict[str, dict[str, object]]] = {}
        for entity_type, urn, aspect_name, value in iter_aspects(bundle):
            grouped.setdefault((entity_type, urn), {})[aspect_name] = value
        for (entity_type, urn), aspects in grouped.items():
            await client.upsert_entity(entity_type, urn, aspects, audit_stamp)
    return {
        "status": "PUBLISHED",
        "catalog_version": bundle["catalog_version"],
        "catalog_sha256": catalog_hash(bundle),
        **aspect_counts(bundle),
    }
