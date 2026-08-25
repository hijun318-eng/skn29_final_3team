"""검증된 live RuntimeCatalogProjection과 product evidence를 비활성 후보로 게시한다.

사전 check에서 승인한 projection checksum이 live read-back과 다시 일치해야 하며,
clean Git source와 명시적 image receipt를 product manifest로 봉인한다. 전용 App DB
publisher identity로 immutable pair만 append하고 active pointer는 변경하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogError  # noqa: E402
from app.adapters.runtime_catalog_candidate_publisher import (  # noqa: E402
    PostgresRuntimeCatalogCandidatePublisher,
    product_release_id_for,
)
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    RUNTIME_CATALOG_PROJECTION_VERSION,
    RuntimeCatalogProjection,
)
from app.capability_contracts import (  # noqa: E402
    CatalogReceipt,
    ImageReceipt,
    MigrationReceipt,
    ModelReceipt,
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
    ProductReleaseVector,
    SourceReceipt,
)
from app.database import normalize_async_database_url  # noqa: E402
from compile_runtime_catalog_projection import (  # noqa: E402
    candidate_receipt,
    compile_live_candidate,
)
from src.ai.model_contracts import (  # noqa: E402
    model_release_checksum,
    model_release_manifest,
)
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


PUBLISHED_CANDIDATE_RECEIPT_VERSION = (
    "answervice.runtime-catalog-published-candidate.v1"
)


class RuntimeCatalogCandidateCommandError(RuntimeError):
    """운영 후보가 안전하게 봉인·게시될 수 없음을 나타낸다."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """사전 승인 checksum과 live read transport, image evidence를 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--datahub-server",
        default=os.getenv("DATAHUB_GMS_URL", "https://127.0.0.1:18081"),
    )
    parser.add_argument(
        "--trino-server",
        default=os.getenv("TRINO_URL", "https://127.0.0.1:18443"),
    )
    parser.add_argument("--trino-user", default=os.getenv("TRINO_RUNTIME_USER"))
    parser.add_argument(
        "--trino-ca-file",
        type=Path,
        default=os.getenv("TRINO_TLS_CA_FILE")
        or os.getenv("TRINO_TLS_CA_HOST_FILE"),
    )
    parser.add_argument(
        "--expected-release",
        default=os.getenv("ANALYTICS_CONTEXT_RELEASE") or None,
    )
    parser.add_argument("--expected-projection-sha256", required=True)
    parser.add_argument("--backend-image-ref", required=True)
    parser.add_argument(
        "--image-receipt",
        action="append",
        default=[],
        metavar="COMPONENT=sha256:DIGEST",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def parse_image_receipts(
    values: list[str],
    backend: ImageReceipt,
) -> tuple[ImageReceipt, ...]:
    """명시적 component digest를 중복 없는 canonical 순서로 검증한다."""

    parsed = {backend.component: backend}
    for value in values:
        component, separator, digest = value.partition("=")
        if not separator or not component or component in parsed:
            raise RuntimeCatalogCandidateCommandError(
                "image receipt is invalid or duplicate"
            )
        parsed[component] = ImageReceipt(component=component, digest=digest)
    return tuple(parsed[name] for name in sorted(parsed))


def verified_backend_image_receipt(
    image_reference: str,
    source: SourceReceipt,
) -> ImageReceipt:
    """OCI source labels가 clean Git receipt와 같은 local Backend image를 검증한다."""

    if not image_reference.strip():
        raise RuntimeCatalogCandidateCommandError(
            "backend image reference is required"
        )
    process = subprocess.run(
        ["docker", "image", "inspect", image_reference],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeCatalogCandidateCommandError(
            "backend image could not be inspected"
        )
    documents = json.loads(process.stdout)
    if not isinstance(documents, list) or len(documents) != 1:
        raise RuntimeCatalogCandidateCommandError(
            "backend image identity is ambiguous"
        )
    document = documents[0]
    if not isinstance(document, dict):
        raise RuntimeCatalogCandidateCommandError(
            "backend image identity is invalid"
        )
    config = document.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        raise RuntimeCatalogCandidateCommandError(
            "backend image provenance is unavailable"
        )
    digest = document.get("Id")
    fingerprint = labels.get("io.answervice.source.fingerprint")
    if (
        labels.get("org.opencontainers.image.revision") != source.commit_sha
        or labels.get("io.answervice.source.dirty") != "false"
        or not isinstance(fingerprint, str)
        or _optional_sha256(fingerprint) is None
        or not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or _optional_sha256(digest.removeprefix("sha256:")) is None
    ):
        raise RuntimeCatalogCandidateCommandError(
            "backend image provenance differs from the clean source"
        )
    return ImageReceipt(component="backend", digest=digest)


def clean_source_receipt() -> tuple[SourceReceipt, datetime]:
    """Repository HEAD와 완전히 clean한 tracked/untracked 상태를 봉인한다."""

    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RuntimeCatalogCandidateCommandError(
            "runtime catalog publication requires a clean source tree"
        )
    revision = _git("rev-parse", "--verify", "HEAD").decode("ascii").strip()
    if len(revision) != 40 or any(value not in "0123456789abcdef" for value in revision):
        raise RuntimeCatalogCandidateCommandError("source revision is invalid")
    timestamp = datetime.fromisoformat(
        _git("show", "-s", "--format=%cI", "HEAD").decode("ascii").strip()
    )
    return SourceReceipt(commit_sha=revision, dirty=False), timestamp


def migration_receipt() -> MigrationReceipt:
    """현재 단일 Alembic head와 전체 migration source chain을 checksum으로 묶는다."""

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    revision = ScriptDirectory.from_config(config).get_current_head()
    if not revision:
        raise RuntimeCatalogCandidateCommandError("migration head is unavailable")
    files = [BACKEND / "alembic.ini", BACKEND / "migrations" / "env.py"]
    files.extend(sorted((BACKEND / "migrations" / "versions").glob("*.py")))
    manifest = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
    return MigrationReceipt(
        revision=revision,
        chain_sha256=canonical_sha256(manifest),
    )


def build_product_manifest(
    projection: RuntimeCatalogProjection,
    *,
    source: SourceReceipt,
    images: tuple[ImageReceipt, ...],
    migration: MigrationReceipt,
    created_at: datetime,
) -> ProductReleaseEvidenceManifest:
    """현재 model/runtime과 exact catalog candidate를 재현 가능한 제품 증거로 봉인한다."""

    model = model_release_manifest()
    model_release_id = str(model["manifest_version"])
    evidence = ProductReleaseEvidence(
        source=source,
        images=images,
        migration=migration,
        model=ModelReceipt(
            release_id=model_release_id,
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
            prompt_release_id=model_release_id,
            policy_release_id=projection.release.policy_version,
            runtime_release_id=(
                f"{RUNTIME_CATALOG_PROJECTION_VERSION}:"
                f"{projection.projection_sha256}"
            ),
        ),
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=product_release_id_for(evidence),
        evidence=evidence,
        created_at=created_at,
    )


async def execute(arguments: argparse.Namespace) -> dict[str, Any]:
    """Fresh live equality를 재확인한 candidate pair만 전용 role로 append한다."""

    expected_projection = _sha256(
        arguments.expected_projection_sha256,
        "expected projection checksum",
    )
    if (
        not isinstance(arguments.expected_release, str)
        or not arguments.expected_release.strip()
    ):
        raise RuntimeCatalogCandidateCommandError(
            "expected catalog release is required"
        )
    database_url = os.getenv("APP_CATALOG_PUBLISHER_DATABASE_URL", "").strip()
    publisher_user = os.getenv("APP_CATALOG_PUBLISHER_USER", "").strip()
    if not database_url:
        raise RuntimeCatalogCandidateCommandError(
            "APP_CATALOG_PUBLISHER_DATABASE_URL is required"
        )
    normalized_database_url = normalize_async_database_url(database_url)
    if not publisher_user or make_url(normalized_database_url).username != publisher_user:
        raise RuntimeCatalogCandidateCommandError(
            "App DB URL does not use the catalog publisher identity"
        )
    source, created_at = clean_source_receipt()
    backend_image = verified_backend_image_receipt(
        arguments.backend_image_ref,
        source,
    )
    images = parse_image_receipts(arguments.image_receipt, backend_image)
    migration = migration_receipt()
    projection, native_readback = await compile_live_candidate(arguments)
    if projection.projection_sha256 != expected_projection:
        raise RuntimeCatalogCandidateCommandError(
            "live runtime catalog candidate differs from the approved check"
        )
    final_source, final_created_at = clean_source_receipt()
    final_migration = migration_receipt()
    if (
        final_source != source
        or final_created_at != created_at
        or final_migration != migration
    ):
        raise RuntimeCatalogCandidateCommandError(
            "source or migration changed during candidate verification"
        )
    manifest = build_product_manifest(
        projection,
        source=source,
        images=images,
        migration=migration,
        created_at=created_at,
    )
    engine = create_async_engine(
        normalized_database_url,
        pool_pre_ping=True,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        published = await PostgresRuntimeCatalogCandidatePublisher(
            sessions
        ).publish_candidate(
            projection,
            manifest,
            expected_migration_revision=migration.revision,
        )
    finally:
        await engine.dispose()
    return {
        **candidate_receipt(projection, native_readback),
        "schema_version": PUBLISHED_CANDIDATE_RECEIPT_VERSION,
        "status": "PUBLISHED_WITHOUT_ACTIVATION",
        "product_release_id": published.product_release_id,
        "product_manifest_sha256": published.product_manifest_sha256,
        "source_commit_sha": source.commit_sha,
        "migration_revision": migration.revision,
        "migration_chain_sha256": migration.chain_sha256,
        "image_receipt_count": len(images),
        "activation_performed": False,
    }


def _git(*arguments: str) -> bytes:
    environment = dict(os.environ)
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    process = subprocess.run(
        [
            "git",
            "-c",
            "core.excludesFile=",
            "-c",
            "core.safecrlf=false",
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeCatalogCandidateCommandError(
            "source receipt could not be computed"
        )
    return process.stdout


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeCatalogCandidateCommandError(
            f"{label} is not a lowercase SHA-256"
        )
    return value


def _optional_sha256(value: object) -> str | None:
    try:
        return _sha256(value, "checksum")
    except RuntimeCatalogCandidateCommandError:
        return None


async def async_main(argv: list[str] | None = None) -> int:
    """게시 결과를 비밀 없는 canonical checksum receipt 한 줄로 출력한다."""

    print(canonical_json(await execute(parse_args(argv))))
    return 0


def main(argv: list[str] | None = None) -> int:
    """예상 가능한 실패를 credential 없는 오류 유형으로 축약한다."""

    try:
        if sys.platform == "win32":
            with asyncio.Runner(
                loop_factory=asyncio.SelectorEventLoop
            ) as runner:
                return runner.run(async_main(argv))
        return asyncio.run(async_main(argv))
    except (OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        output = {"status": "ERROR", "error_type": type(error).__name__}
        if isinstance(error, DataHubCatalogError):
            output["error_category"] = error.category
        print(json.dumps(output, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
