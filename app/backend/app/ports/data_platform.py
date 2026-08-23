"""분석 서비스가 DataHub·Trino 구현 세부사항 없이 의존하는 비동기 데이터 플랫폼 port를 정의한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol


class NoEntitledAssetsError(LookupError):
    """인증된 role·domain 범위에 자연어 요청과 일치하는 승인 asset이 없음을 알린다."""


class NoMetricMatchError(NoEntitledAssetsError):
    """질문에서 승인된 BUSINESS 지표를 특정할 검색 증거가 없음을 알린다."""


class MetadataUnavailableError(RuntimeError):
    """필수 DataHub metadata가 없거나 checksum·schema 검증에 실패해 안전하게 분석할 수 없음을 알린다."""


class ReleaseReceiptChangedError(MetadataUnavailableError):
    """후보 검색 뒤 active semantic release identity가 달라져 같은 분석을 계속할 수 없음을 알린다."""


class UnsupportedSemanticError(ValueError):
    """선택된 catalog release가 요청한 분석 의미를 명시적으로 지원하지 않음을 알린다."""


def _checksum(value: str, name: str) -> None:
    """release receipt checksum이 canonical SHA-256 문자열인지 검증한다."""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 checksum")


@dataclass(frozen=True, order=True)
class GovernedFieldReference:
    """Node 1이 선택했지만 active release에서 다시 확인해야 하는 물리 필드 참조다."""

    asset_fqn: str
    column: str

    def __post_init__(self) -> None:
        """빈 asset·column이 실행 그래프 확장 입력으로 들어오지 못하게 막는다."""

        if (
            not isinstance(self.asset_fqn, str)
            or not self.asset_fqn.strip()
            or not isinstance(self.column, str)
            or not self.column.strip()
        ):
            raise ValueError("governed field reference must be non-empty")


@dataclass(frozen=True)
class AssetCandidateSet:
    """질문 해석용 bounded 후보와 그 후보를 만든 active release receipt를 묶는다.

    ``assets``는 Node 1 힌트일 뿐 실행 권위가 아니다. 실행 전에는 아래 receipt와
    선택 ID를 사용해 DataHub active release 전체에서 subgraph를 다시 해결해야 한다.
    """

    assets: tuple[dict[str, Any], ...]
    context_release: str
    catalog_checksum: str
    canonical_checksum: str
    product_release_id: str | None = None
    runtime_projection_checksum: str | None = None
    source_authority: str | None = None
    retrieval_mode: str | None = None

    def __post_init__(self) -> None:
        """빈 후보나 불완전 release identity를 요청 경계에서 즉시 거부한다."""

        if (
            not isinstance(self.assets, tuple)
            or not self.assets
            or any(not isinstance(item, dict) for item in self.assets)
            or not isinstance(self.context_release, str)
            or not self.context_release.strip()
        ):
            raise ValueError("asset candidate set and context release must be non-empty")
        _checksum(self.catalog_checksum, "catalog checksum")
        _checksum(self.canonical_checksum, "canonical checksum")
        if (self.product_release_id is None) != (
            self.runtime_projection_checksum is None
        ):
            raise ValueError("product release and runtime projection receipts must be paired")
        if self.product_release_id is not None:
            if not self.product_release_id.strip() or len(self.product_release_id) > 160:
                raise ValueError("product release receipt is invalid")
            _checksum(
                self.runtime_projection_checksum,
                "runtime projection checksum",
            )
            if (
                not isinstance(self.source_authority, str)
                or not self.source_authority.strip()
                or not isinstance(self.retrieval_mode, str)
                or not self.retrieval_mode.strip()
            ):
                raise ValueError("candidate source authority and retrieval mode are required")
        elif self.source_authority is not None or self.retrieval_mode is not None:
            if not all(
                isinstance(item, str) and item.strip()
                for item in (self.source_authority, self.retrieval_mode)
            ):
                raise ValueError("candidate source authority or retrieval mode is invalid")


@dataclass(frozen=True)
class ExecutionAssetSelection:
    """Node 1 선택을 active release의 최소 실행 subgraph로 재해결하는 typed 입력이다."""

    output_metric_ids: tuple[str, ...]
    execution_metric_ids: tuple[str, ...]
    field_references: tuple[GovernedFieldReference, ...]
    receipt_context_release: str
    receipt_catalog_checksum: str
    receipt_canonical_checksum: str
    receipt_product_release_id: str | None = None
    receipt_runtime_projection_checksum: str | None = None

    def __post_init__(self) -> None:
        """출력·계산 Metric과 release receipt의 최소 불변식을 검증한다."""

        if (
            not 1 <= len(self.output_metric_ids) <= 4
            or len(set(self.output_metric_ids)) != len(self.output_metric_ids)
            or not self.execution_metric_ids
            or len(set(self.execution_metric_ids)) != len(self.execution_metric_ids)
            or not set(self.output_metric_ids).issubset(self.execution_metric_ids)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in self.execution_metric_ids
            )
            or len(set(self.field_references)) != len(self.field_references)
            or tuple(sorted(self.field_references)) != self.field_references
            or not isinstance(self.receipt_context_release, str)
            or not self.receipt_context_release.strip()
        ):
            raise ValueError("execution asset selection is incomplete or non-canonical")
        _checksum(self.receipt_catalog_checksum, "receipt catalog checksum")
        _checksum(self.receipt_canonical_checksum, "receipt canonical checksum")
        if (self.receipt_product_release_id is None) != (
            self.receipt_runtime_projection_checksum is None
        ):
            raise ValueError("product release and runtime projection receipts must be paired")
        if self.receipt_product_release_id is not None:
            if (
                not self.receipt_product_release_id.strip()
                or len(self.receipt_product_release_id) > 160
            ):
                raise ValueError("product release receipt is invalid")
            _checksum(
                self.receipt_runtime_projection_checksum,
                "receipt runtime projection checksum",
            )


class DataPlatformAdapter(Protocol):
    """분석 서비스가 사용할 수 있는 데이터 플랫폼 기능의 최소 계약이다.

    구현체는 DataHub에서 권한과 schema를 확인하고 Trino를 통해서만 읽는다.
    서비스 계층이 source DB 연결 정보나 외부 client 세부사항에 의존하지 않게
    만드는 신뢰 경계이며, 실패를 빈 결과로 바꾸지 않는다.
    """

    async def search_asset_candidates(
        self,
        query: str,
        context: dict[str, Any],
    ) -> AssetCandidateSet:
        """실행 값을 바인딩하지 않은 승인 후보와 immutable release receipt를 반환한다."""
        ...

    async def resolve_execution_assets(
        self,
        selection: ExecutionAssetSelection,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """선택 ID를 active release에 재결속해 권한·JOIN·schema 검증된 subgraph를 반환한다."""
        ...

    async def get_metric_terms(
        self,
        metric_ids: tuple[str, ...],
        context: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """고유한 metric id들을 active DataHub release의 승인 용어 정의로 해석한다."""
        ...

    async def get_asset_schema(
        self,
        urn: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """URN asset의 governed column과 live Trino가 일치할 때만 schema payload를 반환한다."""
        ...

    async def get_active_context_release(self) -> str:
        """현재 완전 검증된 DataHub catalog release 식별자를 반환한다."""
        ...

    async def get_catalog_readiness(self) -> tuple[dict[str, str], str | None]:
        """semantic release·manifest·Trino schema 상태와 검증 receipt를 반환한다."""
        ...

    async def get_product_release_readiness(
        self,
        product_release_id: str,
    ) -> tuple[dict[str, str], str | None, str | None]:
        """고정 product release의 readiness receipt와 semantic release를 반환한다."""
        ...

    async def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        """parameter binding이 끝나고 capability로 승인된 exact SQL을 실행해 typed evidence를 반환한다."""
        ...

    async def execute_auxiliary_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        """동일 실행 가드를 쓰되 본 분석 lifecycle attempt와 분리된 Context query를 실행한다."""
        ...

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        """query id의 bounded terminal 상태를 조회하고 알려지지 않은 id는 명시적으로 구분한다."""
        ...

    async def cancel_query(self, query_id: str) -> dict[str, Any]:
        """진행 중인 query를 coordinator와 local state에서 취소하고 terminal 결과를 반환한다."""
        ...

    async def cancel_query_at(
        self,
        query_id: str,
        cancel_uri: str,
    ) -> dict[str, Any]:
        """durable same-query coordinator URI로 재시작 뒤 orphan query를 취소한다."""
        ...

    def bind_query_lifecycle(
        self,
        sink: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        """현재 request의 query submission·heartbeat·terminal evidence sink를 결속한다."""
        ...

    async def get_source_health(self) -> list[dict[str, Any]]:
        """DataHub·Trino 각 source의 독립적인 readiness 상태를 반환한다."""
        ...

    async def aclose(self) -> None:
        """port 구현체가 소유한 비동기 외부 resource를 정상 종료한다."""
        ...
