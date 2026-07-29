from __future__ import annotations

from typing import Any, Protocol


class DataPlatformAdapter(Protocol):
    """R2-owned Port. R4 consumes this interface only; it never opens source DB connections."""

    def search_assets(self, query: str, context: dict[str, Any]) -> list[dict[str, Any]]: ...

    def get_asset_schema(self, urn: str) -> dict[str, Any]: ...

    def execute_query(
        self, sql: str, parameters: dict[str, Any], gate_token: str
    ) -> dict[str, Any]: ...

    def get_query_status(self, query_id: str) -> dict[str, Any]: ...

    def cancel_query(self, query_id: str) -> dict[str, Any]: ...

    def get_source_health(self) -> list[dict[str, Any]]: ...
