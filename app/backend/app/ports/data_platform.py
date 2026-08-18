"""분석 서비스가 DataHub·Trino 구현 세부사항 없이 의존하는 비동기 데이터 플랫폼 port를 정의한다."""

from __future__ import annotations

from typing import Any, Protocol


class NoEntitledAssetsError(LookupError):
    """인증된 role·domain 범위에 자연어 요청과 일치하는 승인 asset이 없음을 알린다."""


class MetadataUnavailableError(RuntimeError):
    """필수 DataHub metadata가 없거나 checksum·schema 검증에 실패해 안전하게 분석할 수 없음을 알린다."""


class UnsupportedSemanticError(ValueError):
    """선택된 catalog release가 요청한 분석 의미를 명시적으로 지원하지 않음을 알린다."""


class DataPlatformAdapter(Protocol):
    """분석 서비스가 사용할 수 있는 데이터 플랫폼 기능의 최소 계약이다.

    구현체는 DataHub에서 권한과 schema를 확인하고 Trino를 통해서만 읽는다.
    서비스 계층이 source DB 연결 정보나 외부 client 세부사항에 의존하지 않게
    만드는 신뢰 경계이며, 실패를 빈 결과로 바꾸지 않는다.
    """

    async def search_assets(
        self,
        query: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """자연어와 인증 context로 승인 asset을 찾아 권한·schema 검증된 runtime 계약을 반환한다."""
        ...

    async def get_metric_terms(
        self, metric_ids: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        """고유한 metric id들을 active DataHub release의 승인 용어 정의로 해석한다."""
        ...

    async def get_asset_schema(self, urn: str) -> dict[str, Any]:
        """URN asset의 governed column과 live Trino가 일치할 때만 schema payload를 반환한다."""
        ...

    async def get_active_context_release(self) -> str:
        """현재 완전 검증된 DataHub catalog release 식별자를 반환한다."""
        ...

    async def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]:
        """parameter binding이 끝나고 capability로 승인된 exact SQL을 실행해 typed evidence를 반환한다."""
        ...

    async def get_query_status(self, query_id: str) -> dict[str, Any]:
        """query id의 bounded terminal 상태를 조회하고 알려지지 않은 id는 명시적으로 구분한다."""
        ...

    async def cancel_query(self, query_id: str) -> dict[str, Any]:
        """진행 중인 query를 coordinator와 local state에서 취소하고 terminal 결과를 반환한다."""
        ...

    async def get_source_health(self) -> list[dict[str, Any]]:
        """DataHub·Trino 각 source의 독립적인 readiness 상태를 반환한다."""
        ...

    async def aclose(self) -> None:
        """port 구현체가 소유한 비동기 외부 resource를 정상 종료한다."""
        ...
