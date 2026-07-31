from __future__ import annotations

import hashlib
import re
from uuid import NAMESPACE_URL, UUID, uuid5

from app.contracts import AnalysisRequest, RequestContext, SourceReference
from app.ports.data_platform import DataPlatformAdapter
from app.services.context_builder import (
    ContextAsset,
    ContextBuildRequest,
    ContextPackage,
    ContextPackageBuilder,
)


class PipelineSupport:
    """Context, G2, 식별자 생성처럼 상태 전이와 무관한 순수 보조 로직."""

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        context_builder: ContextPackageBuilder,
    ) -> None:
        self._adapter = adapter
        self._context_builder = context_builder

    def build_context(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
    ) -> ContextPackage:
        items = tuple(
            ContextAsset(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                columns=tuple(
                    str(column["name"])
                    for column in self._adapter.get_asset_schema(
                        str(asset["urn"])
                    )["columns"]
                ),
            )
            for asset in assets
        )
        request = ContextBuildRequest(
            context_release="context-v1",
            policy_version="policy-v1",
            time_version=context.as_of.isoformat(),
            entitlement_hash=hashlib.sha256(
                f"{context.user_id}:{context.role.value}".encode()
            ).hexdigest(),
            assets=items,
            token_count=max(1, len(payload.question.split()) * 4),
            model_context_tokens=24_000,
        )
        return self._context_builder.build(
            request,
            frozenset(item.urn for item in items),
        )

    @staticmethod
    def g2_violation(
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        sql = str(plan.get("sql", "")).strip()
        normalized = sql.lower()
        forbidden = {
            "insert",
            "update",
            "delete",
            "drop",
            "alter",
            "create",
            "grant",
            "revoke",
            "call",
            "merge",
        }
        tokens = set(re.findall(r"[a-z_]+", normalized))
        if (
            not normalized.startswith("select ")
            or ";" in normalized
            or tokens.intersection(forbidden)
        ):
            return "UNSAFE_SQL"
        allowed = {item.fqn for item in package.assets}
        references = plan.get("references")
        if not isinstance(references, list) or not references:
            return "REFERENCE_MISSING"
        referenced = {str(item.get("fqn")) for item in references}
        if not referenced.issubset(allowed):
            return "REFERENCE_OUTSIDE_CONTEXT"
        queried = {
            table.strip('"').lower()
            for table in re.findall(
                r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)",
                sql,
                flags=re.IGNORECASE,
            )
        }
        if queried != {item.lower() for item in referenced}:
            return "SQL_REFERENCE_MISMATCH"
        return None

    @staticmethod
    def gate_token(package: ContextPackage, sql: str) -> str:
        return hashlib.sha256(
            f"{package.package_hash}:{sql}".encode()
        ).hexdigest()

    @staticmethod
    def artifact_id(
        trace_id: str,
        query_id: str,
        context_hash: str,
    ) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"{trace_id}:{query_id}:{context_hash}",
        )

    @staticmethod
    def sources(
        assets: list[dict[str, object]],
    ) -> tuple[SourceReference, ...]:
        return tuple(
            SourceReference(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                name=str(asset["name"]),
                schema_version=str(asset["schema_version"]),
                seed_version=str(asset["seed_version"]),
            )
            for asset in assets
        )
