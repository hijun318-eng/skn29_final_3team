"""현재 DataHub Dataset custom-properties snapshot을 canonical semantic release로 변환한다."""

from __future__ import annotations

from app.adapters.catalog_snapshot import CatalogSnapshot
from app.adapters.datahub_metadata_values import GovernedMetadataError
from app.adapters.release_manifest import (
    coherent_release_datasets,
    validated_release_bundle,
)
from app.services.context.semantic_release import (
    CanonicalSemanticRelease,
    CanonicalSemanticReleaseError,
)


LEGACY_DATAHUB_SOURCE_KIND = "datahub_dataset_custom_properties"


def compile_legacy_semantic_release(
    snapshot: CatalogSnapshot,
    expected_release: str | None = None,
) -> CanonicalSemanticRelease:
    """manifest·membership·checksum 검증을 통과한 Legacy snapshot만 canonical release로 컴파일한다."""

    datasets = coherent_release_datasets(snapshot, expected_release)
    bundle = validated_release_bundle(snapshot, datasets)
    try:
        release = CanonicalSemanticRelease.from_validated_bundle(
            bundle,
            runtime_contract_version=datasets[0].contract_version,
            source_kind=LEGACY_DATAHUB_SOURCE_KIND,
        )
    except CanonicalSemanticReleaseError as error:
        raise GovernedMetadataError(
            "DataHub legacy release cannot be compiled into the canonical contract"
        ) from error
    if (
        release.catalog_version != datasets[0].context_release
        or release.policy_version != datasets[0].policy_version
        or release.catalog_checksum != datasets[0].catalog_checksum
        or release.manifest_checksum != datasets[0].manifest_checksum
    ):
        raise GovernedMetadataError(
            "DataHub legacy release identity differs after canonical compilation"
        )
    return release
