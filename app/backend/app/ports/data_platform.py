from __future__ import annotations

from typing import Any, Protocol


class DataPlatformAccessDenied(ValueError):
    pass


class DataPlatformUnavailable(ValueError):
    pass


class DataPlatformNoAssets(ValueError):
    pass


class DataPlatformAdapter(Protocol):
    """R2-owned Port. R4 consumes this interface only; it never opens source DB connections."""

    def search_assets(self, query: str, context: dict[str, Any]) -> list[dict[str, Any]]: ...

    def get_asset_schema(self, urn: str) -> dict[str, Any]: ...

    def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any],
        gate_token: str,
        trino_principal: str | None = None,
    ) -> dict[str, Any]: ...

    def get_query_status(self, query_id: str) -> dict[str, Any]: ...

    def cancel_query(self, query_id: str) -> dict[str, Any]: ...

    def get_source_watermarks(
        self,
        source_ids: frozenset[str],
        trino_principal: str | None = None,
    ) -> dict[str, str]: ...

    def get_source_health(self) -> list[dict[str, Any]]: ...
