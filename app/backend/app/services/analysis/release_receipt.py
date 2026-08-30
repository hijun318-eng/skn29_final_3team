"""분석 API와 보고서 재실행이 공유하는 active product·semantic release 판독 경계다."""

from __future__ import annotations

from typing import Protocol


class ActiveReleasePlatform(Protocol):
    """active semantic pointer와 executable product readiness를 제공하는 최소 포트다."""

    async def get_active_context_release(self) -> str:
        """현재 active semantic release ID를 반환한다."""
        ...

    async def get_catalog_readiness(self) -> tuple[dict[str, str], str]:
        """필수 stage readiness와 결속된 product release ID를 반환한다."""
        ...


class ActiveReleaseUnavailable(ValueError):
    """active pointer를 안정된 executable 영수증으로 읽지 못했음을 나타낸다."""


async def active_product_release_receipt(
    platform: ActiveReleasePlatform,
) -> tuple[str, str]:
    """pointer drift와 미준비 stage를 차단해 product·semantic pair를 원자적으로 읽는다."""

    semantic_before = await platform.get_active_context_release()
    stages, product_release = await platform.get_catalog_readiness()
    semantic_after = await platform.get_active_context_release()
    if (
        semantic_before != semantic_after
        or not semantic_before
        or not product_release
        or not stages
        or any(value != "ready" for value in stages.values())
    ):
        raise ActiveReleaseUnavailable(
            "active product release receipt is not stable and executable"
        )
    return product_release, semantic_after
