"""분석 요청·재실행 run을 idempotency key와 server Context snapshot으로 시작 상태에 기록한다."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.adapters.analysis_repository_common import (
    AnalysisRepositoryUnavailable,
    _hash,
    _redact_question,
    _uuid,
)
from app.contracts import RequestContext

if TYPE_CHECKING:
    from app.services.context.builder import ContextPackage


class AnalysisRunStartRepositoryMixin:
    """분석 요청과 정의-version run link를 한 transaction에서 시작 상태로 기록한다.

    저장소 조합체의 소유자 ID를 actor로 고정하고 server ``RequestContext`` snapshot을
    보존한다. 정의 재실행은 idempotency key로 기존 request ID를 재사용하며 DB 장애는
    :class:`AnalysisRepositoryUnavailable`로 변환한다.
    """
    async def begin_run(
        self,
        definition: dict[str, Any],
        context: RequestContext,
        as_of: date,
        idempotency_key: str,
        parameters: dict[str, object] | None = None,
    ) -> tuple[UUID, bool]:
        """실행 처리를 중복 실행 방지 조건과 함께 시작한다."""
        definition_id = _uuid(definition["definition_id"], "definition_id")
        receipt = (
            context.product_release_id,
            context.permission_snapshot_id,
            context.semantic_release_id,
        )
        if not all(receipt):
            raise ValueError("Analysis replay receipt가 완전하지 않습니다.")
        try:
            async with self._sessionmaker.begin() as session:
                existing = (await session.execute(
                    text(
                        """
                        SELECT l.request_id
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        WHERE l.definition_id = :definition_id
                          AND l.definition_version = :version
                          AND l.idempotency_key = :idempotency_key
                          AND d.owner_id = :owner_id
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": definition["version"],
                        "idempotency_key": idempotency_key,
                        "owner_id": self._owner_id,
                    },
                )).scalar_one_or_none()
                if existing:
                    return UUID(str(existing)), False
                await session.execute(
                    text(
                        """
                        INSERT INTO chat.analysis_requests
                            (request_id, conversation_id, command_id,
                             request_type, user_id, user_role,
                             question_text_redacted, question_hash, ambiguity_status,
                             sql_policy_version, status, trace_id, started_at,
                             product_release_id, permission_snapshot_id,
                             semantic_release_id)
                        VALUES (:request_id, :conversation_id, :command_id,
                                'CHAT', :user_id, :user_role,
                                :question, :question_hash, 'CLEAR',
                                'policy-v1', 'RECEIVED', :trace_id, :started_at,
                                :product_release_id, :permission_snapshot_id,
                                :semantic_release_id)
                        """
                    ),
                    {
                        "request_id": context.request_id,
                        "conversation_id": context.conversation_id,
                        "command_id": context.command_id,
                        "user_id": self._owner_id,
                        "user_role": context.role.value,
                        "question": definition["question"],
                        "question_hash": _hash(definition["question"]),
                        "trace_id": context.trace_id,
                        "started_at": datetime.now(timezone.utc),
                        "product_release_id": context.product_release_id,
                        "permission_snapshot_id": context.permission_snapshot_id,
                        "semantic_release_id": context.semantic_release_id,
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_run_links
                            (definition_id, definition_version, request_id,
                             idempotency_key, as_of, timezone_name,
                             parameters_json, parameter_hash)
                        VALUES (:definition_id, :version, :request_id,
                                :idempotency_key, :as_of, :timezone,
                                CAST(:parameters AS jsonb), :parameter_hash)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": definition["version"],
                        "request_id": context.request_id,
                        "idempotency_key": idempotency_key,
                        "as_of": as_of,
                        "timezone": context.timezone,
                        "parameters": json.dumps(
                            parameters if parameters is not None else definition["parameters"],
                            ensure_ascii=False,
                        ),
                        "parameter_hash": _hash(
                            parameters if parameters is not None else definition["parameters"]
                        ),
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO governance.product_release_bindings (
                            object_kind, object_id, product_release_id,
                            permission_snapshot_id, semantic_release_id,
                            capability_release_vector_json, evidence_refs_json
                        ) VALUES (
                            'RUN', :object_id, :product_release_id,
                            :permission_snapshot_id, :semantic_release_id,
                            '{"analysis.run":"1.0.0"}'::jsonb, '[]'::jsonb
                        )
                        """
                    ),
                    {
                        "object_id": str(context.request_id),
                        "product_release_id": context.product_release_id,
                        "permission_snapshot_id": context.permission_snapshot_id,
                        "semantic_release_id": context.semantic_release_id,
                    },
                )
                return context.request_id, True
        except IntegrityError as error:
            try:
                existing = await self._existing_run(definition_id, definition["version"], idempotency_key)
            except (KeyError, SQLAlchemyError) as lookup_error:
                raise AnalysisRepositoryUnavailable(
                    "Analysis 실행을 예약할 수 없습니다."
                ) from lookup_error
            return existing, False
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error

    async def begin_request(
        self,
        question: str,
        parameters: dict[str, object],
        context: RequestContext,
    ) -> UUID:
        """요청 처리를 중복 실행 방지 조건과 함께 시작한다."""
        redacted = _redact_question(question)
        if not redacted:
            raise ValueError("redacted question은 비어 있을 수 없습니다.")
        definition_id = uuid4()
        try:
            async with self._sessionmaker.begin() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_definitions
                            (definition_id, version, owner_id, title,
                             question_text_redacted, parameters_json, parameter_hash,
                             is_saved)
                        VALUES (:definition_id, 1, :owner_id, :title,
                                :question, CAST(:parameters AS jsonb), :parameter_hash,
                                false)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "owner_id": self._owner_id,
                        "title": "Analysis request",
                        "question": redacted,
                        "parameters": json.dumps(parameters),
                        "parameter_hash": _hash(parameters),
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO chat.analysis_requests
                            (request_id, conversation_id, command_id,
                             request_type, user_id, user_role,
                             question_text_redacted, question_hash, ambiguity_status,
                             sql_policy_version, status, trace_id, started_at,
                             product_release_id, permission_snapshot_id,
                             semantic_release_id)
                        VALUES (:request_id, :conversation_id, :command_id,
                                'CHAT', :user_id, :user_role,
                                :question, :question_hash, 'CLEAR',
                                'policy-v1', 'RECEIVED', :trace_id, :started_at,
                                :product_release_id, :permission_snapshot_id,
                                :semantic_release_id)
                        """
                    ),
                    {
                        "request_id": context.request_id,
                        "conversation_id": context.conversation_id,
                        "command_id": context.command_id,
                        "user_id": self._owner_id,
                        "user_role": context.role.value,
                        "question": redacted,
                        "question_hash": _hash(redacted),
                        "trace_id": context.trace_id,
                        "started_at": datetime.now(timezone.utc),
                        "product_release_id": context.product_release_id,
                        "permission_snapshot_id": context.permission_snapshot_id,
                        "semantic_release_id": context.semantic_release_id,
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_run_links
                            (definition_id, definition_version, request_id,
                             idempotency_key, as_of, timezone_name,
                             parameters_json, parameter_hash)
                        VALUES (:definition_id, 1, :request_id,
                                :idempotency_key, :as_of, :timezone,
                                CAST(:parameters AS jsonb), :parameter_hash)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "request_id": context.request_id,
                        "idempotency_key": str(context.request_id),
                        "as_of": context.as_of,
                        "timezone": context.timezone,
                        "parameters": json.dumps(parameters, ensure_ascii=False),
                        "parameter_hash": _hash(parameters),
                    },
                )
                receipt = (
                    context.product_release_id,
                    context.permission_snapshot_id,
                    context.semantic_release_id,
                )
                if context.command_id is not None or any(receipt):
                    if not all(
                        (
                            context.product_release_id,
                            context.permission_snapshot_id,
                            context.semantic_release_id,
                        )
                    ):
                        raise ValueError("Analysis Run receipt가 완전하지 않습니다.")
                    if context.command_id is not None and context.conversation_id is None:
                        raise ValueError("Conversation Analysis identity가 완전하지 않습니다.")
                    await session.execute(
                        text(
                            """
                            INSERT INTO governance.product_release_bindings (
                                object_kind, object_id, product_release_id,
                                permission_snapshot_id, semantic_release_id,
                                capability_release_vector_json, evidence_refs_json
                            ) VALUES (
                                'RUN', :object_id, :product_release_id,
                                :permission_snapshot_id, :semantic_release_id,
                                '{"analysis.run":"1.0.0"}'::jsonb, '[]'::jsonb
                            )
                            """
                        ),
                        {
                            "object_id": str(context.request_id),
                            "product_release_id": context.product_release_id,
                            "permission_snapshot_id": context.permission_snapshot_id,
                            "semantic_release_id": context.semantic_release_id,
                        },
                    )
            return context.request_id
        except IntegrityError as error:
            raise ValueError("같은 Analysis request가 이미 존재합니다.") from error
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 요청을 저장할 수 없습니다.") from error

    async def persist_context_receipt(
        self,
        context: RequestContext,
        package: ContextPackage,
    ) -> UUID:
        """DataHub runtime context를 불변 Run 영수증으로 원자적으로 연결한다."""

        receipt = (
            context.product_release_id,
            context.permission_snapshot_id,
            context.semantic_release_id,
        )
        if not all(receipt):
            raise ValueError("Runtime Context release receipt가 완전하지 않습니다.")
        if (
            package.product_release_id != context.product_release_id
            or package.context_release != context.semantic_release_id
        ):
            raise ValueError("Runtime Context와 Analysis Run release가 일치하지 않습니다.")

        def normalized(value: object) -> object:
            return json.loads(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            )

        user_scope = normalized(
            {
                "user_id": str(context.user_id),
                "role": context.role.value,
                "entitlement_hash": package.entitlement_hash,
            }
        )
        assets = normalized([asdict(item) for item in package.assets])
        metrics = normalized([asdict(item) for item in package.metrics])
        joins = normalized(
            [item.as_dict() for item in getattr(package, "join_graph", ())]
        )
        policy_receipt = {
                    "policy_version": package.policy_version,
                    "time_version": package.time_version,
                    "evidence_cutoff": package.evidence_cutoff,
                    "parameter_bindings": [
                        asdict(item) for item in package.parameter_bindings
                    ],
                    "required_filters": [
                        asdict(item) for item in package.required_filters
                    ],
                    "metric_terms": [asdict(item) for item in package.metric_terms],
                    "runtime_contracts": getattr(package, "runtime_contracts", None),
                    "query_strategy": getattr(package, "query_strategy", ""),
                }
        if package.dimension_member_receipts:
            policy_receipt["dimension_member_receipts"] = [
                asdict(item) for item in package.dimension_member_receipts
            ]
        policies = normalized([policy_receipt])
        expected_payload = {
            "user_scope_json": user_scope,
            "assets_json": assets,
            "metrics_json": metrics,
            "joins_json": joins,
            "policies_json": policies,
            "dataset_count": package.dataset_count,
            "column_count": package.column_count,
            "token_count": package.token_count,
            "package_hash": package.package_hash,
            "product_release_id": context.product_release_id,
            "permission_snapshot_id": context.permission_snapshot_id,
            "semantic_release_id": context.semantic_release_id,
        }
        package_id = uuid4()
        idempotency_key = f"runtime:{context.request_id}"
        try:
            async with self._sessionmaker.begin() as session:
                run = (
                    await session.execute(
                        text(
                            """
                            SELECT context_package_id, product_release_id,
                                   permission_snapshot_id, semantic_release_id
                            FROM chat.analysis_requests
                            WHERE request_id = :request_id AND user_id = :owner_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "request_id": context.request_id,
                            "owner_id": self._owner_id,
                        },
                    )
                ).mappings().one_or_none()
                if run is None:
                    raise ValueError("Runtime Context를 연결할 Analysis Run이 없습니다.")
                if (
                    run["product_release_id"],
                    run["permission_snapshot_id"],
                    run["semantic_release_id"],
                ) != receipt:
                    raise ValueError("저장된 Analysis Run release receipt가 다릅니다.")

                row = (
                    await session.execute(
                        text(
                            """
                            INSERT INTO context.context_packages (
                                context_package_id, request_id, context_release_id,
                                user_scope_json, assets_json, metrics_json,
                                joins_json, policies_json, dataset_count,
                                column_count, token_count, package_hash,
                                idempotency_key, product_release_id,
                                permission_snapshot_id, semantic_release_id
                            ) VALUES (
                                :context_package_id, :request_id, NULL,
                                CAST(:user_scope AS jsonb), CAST(:assets AS jsonb),
                                CAST(:metrics AS jsonb), CAST(:joins AS jsonb),
                                CAST(:policies AS jsonb), :dataset_count,
                                :column_count, :token_count, :package_hash,
                                :idempotency_key, :product_release_id,
                                :permission_snapshot_id, :semantic_release_id
                            )
                            ON CONFLICT (request_id) DO NOTHING
                            RETURNING *
                            """
                        ),
                        {
                            "context_package_id": package_id,
                            "request_id": context.request_id,
                            "user_scope": json.dumps(user_scope, ensure_ascii=False),
                            "assets": json.dumps(assets, ensure_ascii=False),
                            "metrics": json.dumps(metrics, ensure_ascii=False),
                            "joins": json.dumps(joins, ensure_ascii=False),
                            "policies": json.dumps(policies, ensure_ascii=False),
                            "dataset_count": package.dataset_count,
                            "column_count": package.column_count,
                            "token_count": package.token_count,
                            "package_hash": package.package_hash,
                            "idempotency_key": idempotency_key,
                            "product_release_id": context.product_release_id,
                            "permission_snapshot_id": context.permission_snapshot_id,
                            "semantic_release_id": context.semantic_release_id,
                        },
                    )
                ).mappings().one_or_none()
                if row is None:
                    row = (
                        await session.execute(
                            text(
                                "SELECT * FROM context.context_packages "
                                "WHERE request_id = :request_id"
                            ),
                            {"request_id": context.request_id},
                        )
                    ).mappings().one()
                if row["context_release_id"] is not None:
                    raise ValueError("Analysis Run이 과거 Context Registry package에 연결됐습니다.")
                if row["idempotency_key"] != idempotency_key or any(
                    row[column] != value
                    for column, value in expected_payload.items()
                ):
                    raise ValueError("같은 Analysis Run의 Runtime Context 영수증이 다릅니다.")
                package_id = UUID(str(row["context_package_id"]))

                await session.execute(
                    text(
                        """
                        INSERT INTO governance.product_release_bindings (
                            object_kind, object_id, product_release_id,
                            permission_snapshot_id, semantic_release_id,
                            capability_release_vector_json, evidence_refs_json
                        ) VALUES (
                            'CONTEXT', :object_id, :product_release_id,
                            :permission_snapshot_id, :semantic_release_id,
                            '{"context.package":"1.0.0"}'::jsonb,
                            CAST(:evidence_refs AS jsonb)
                        )
                        ON CONFLICT (object_kind, object_id) DO NOTHING
                        """
                    ),
                    {
                        "object_id": str(package_id),
                        "product_release_id": context.product_release_id,
                        "permission_snapshot_id": context.permission_snapshot_id,
                        "semantic_release_id": context.semantic_release_id,
                        "evidence_refs": json.dumps(
                            [
                                {
                                    "kind": "RUNTIME_CONTEXT_PACKAGE",
                                    "package_hash": package.package_hash,
                                    "semantic_authority": (
                                        "DATAHUB_RUNTIME_CATALOG_PROJECTION"
                                    ),
                                }
                            ],
                            sort_keys=True,
                        ),
                    },
                )
                binding = (
                    await session.execute(
                        text(
                            """
                            SELECT product_release_id, permission_snapshot_id,
                                   semantic_release_id
                            FROM governance.product_release_bindings
                            WHERE object_kind = 'CONTEXT' AND object_id = :object_id
                            """
                        ),
                        {"object_id": str(package_id)},
                    )
                ).mappings().one()
                if (
                    binding["product_release_id"],
                    binding["permission_snapshot_id"],
                    binding["semantic_release_id"],
                ) != receipt:
                    raise ValueError("Runtime Context product release binding이 다릅니다.")

                linked = (
                    await session.execute(
                        text(
                            """
                            UPDATE chat.analysis_requests
                            SET context_package_id = :context_package_id
                            WHERE request_id = :request_id
                              AND user_id = :owner_id
                              AND (
                                  context_package_id IS NULL
                                  OR context_package_id = :context_package_id
                              )
                            RETURNING context_package_id
                            """
                        ),
                        {
                            "context_package_id": package_id,
                            "request_id": context.request_id,
                            "owner_id": self._owner_id,
                        },
                    )
                ).scalar_one_or_none()
                if linked is None:
                    raise ValueError("Analysis Run의 Runtime Context 연결이 다릅니다.")
                return package_id
        except ValueError:
            raise
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable(
                "Runtime Context 영수증을 저장할 수 없습니다."
            ) from error

    async def _existing_run(
        self,
        definition_id: UUID,
        version: int,
        idempotency_key: str,
    ) -> UUID:
        async with self._sessionmaker() as session:
            request_id = (await session.execute(
                text(
                    """
                    SELECT l.request_id
                    FROM analysis_v1.analysis_run_links l
                    JOIN analysis_v1.analysis_definitions d
                      ON d.definition_id = l.definition_id
                     AND d.version = l.definition_version
                    WHERE l.definition_id = :definition_id
                      AND l.definition_version = :version
                      AND l.idempotency_key = :idempotency_key
                      AND d.owner_id = :owner_id
                    """
                ),
                {
                    "definition_id": definition_id,
                    "version": version,
                    "idempotency_key": idempotency_key,
                    "owner_id": self._owner_id,
                },
            )).scalar_one_or_none()
        if request_id is None:
            raise KeyError("idempotent Analysis Run을 찾을 수 없습니다.")
        return UUID(str(request_id))
