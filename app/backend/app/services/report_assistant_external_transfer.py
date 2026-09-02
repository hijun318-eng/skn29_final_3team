"""Report Assistant 모델 전송의 명시 동의와 호출별 hash receipt 경계를 제공한다."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from app.report_contracts import (
    ReportAssistantExternalTransferConsentResponse,
    ReportAssistantExternalTransferDisclosureResponse,
)
from src.modelops.runtime_config import (
    ActiveModelRoute,
    active_route_for_node,
    resolve_active_model_routes,
)


EXTERNAL_TRANSFER_POLICY_VERSION = "REPORT-ASSISTANT-TRANSFER-v1.0.0"
_DISCLOSURE_LIFETIME = timedelta(minutes=15)
_REPORT_ASSISTANT_NODES = frozenset(
    {"report_assistant", "report_assistant_turn", "report_assistant_review"}
)
_SCOPE_ORDER = (
    "user_instruction",
    "assistant_turn_history",
    "report_metadata_layout",
    "report_block_content",
    "selected_artifact_metadata",
    "selected_artifact_narrative",
    "selected_artifact_metrics",
    "selected_artifact_chart_spec",
    "selected_artifact_table_snapshot",
    "pending_patch",
    "approved_new_analysis_artifact",
)
_EXCLUDED_DATA = (
    "서버가 별도 보유한 인증 토큰·비밀번호 필드",
    "서버가 별도 보유한 데이터베이스·SQL 연결 자격 증명 필드",
    "선택한 승인 Artifact 밖의 원본 데이터베이스 행",
)
_CONTENT_WARNING = (
    "사용자 지시·대화·보고서·선택 Artifact 원문에 민감정보가 포함되어 있으면 "
    "그 내용도 함께 전송될 수 있으므로 동의 전에 검토하고 제거해 주세요."
)
_DEPLOYMENT_PREAPPROVAL_ENV = "REPORT_ASSISTANT_EXTERNAL_TRANSFER_PREAUTHORIZED"


def _deployment_preapproval_enabled() -> bool:
    """배포자가 명시한 true만 외부 전송 사전 승인을 활성화한다."""

    value = os.getenv(_DEPLOYMENT_PREAPPROVAL_ENV, "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{_DEPLOYMENT_PREAPPROVAL_ENV} must be true or false")
    return value == "true"


class ExternalTransferConsentRequired(RuntimeError):
    """외부 route에 현재 세션 결속과 일치하는 명시 동의가 없음을 알린다."""

    def __init__(
        self, disclosure: ReportAssistantExternalTransferDisclosureResponse
    ) -> None:
        super().__init__("Report Assistant external transfer consent is required")
        self.disclosure = disclosure


def _canonical_sha256(value: object) -> str:
    """원문을 보존하지 않는 안정적인 JSON canonical SHA-256을 반환한다."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _json_object(value: object, label: str) -> dict[str, Any]:
    """DB JSONB 또는 JSON 문자열을 공개문 객체로 엄격히 해석한다."""

    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} is invalid")
    return parsed


def _json_sequence(value: object, label: str) -> tuple[str, ...]:
    """DB JSONB 또는 JSON 문자열의 중복 없는 문자열 배열만 허용한다."""

    parsed = json.loads(value) if isinstance(value, str) else value
    if (
        not isinstance(parsed, (list, tuple))
        or not parsed
        or any(not isinstance(item, str) or not item for item in parsed)
        or len(parsed) != len(set(parsed))
    ):
        raise ValueError(f"{label} is invalid")
    return tuple(parsed)


def _utc_datetime(value: object, label: str) -> datetime:
    """DB timestamptz 또는 ISO-8601 값을 UTC aware datetime으로 엄격히 정규화한다."""

    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError(f"{label} is invalid")
    return parsed.astimezone(timezone.utc)


def _public_provider_routes(route: ActiveModelRoute) -> tuple[dict[str, str], ...]:
    """승인 목적지의 공개 가능한 Report Assistant route 노드만 반환한다."""

    nodes = tuple(node for node in route.nodes if node in _REPORT_ASSISTANT_NODES)
    if not nodes:
        raise ValueError("Report Assistant route does not cover an Assistant node")
    parsed = urlsplit(route.endpoint)
    port = f":{parsed.port}" if parsed.port is not None else ""
    destination_origin = f"https://{parsed.hostname.lower()}{port}"
    if destination_origin not in route.approved_endpoint_origins:
        raise ValueError("Report Assistant destination origin is not approved")
    if not route.route_label:
        raise ValueError("Report Assistant route label is missing")
    return tuple(
        {
            "node": node,
            "route_id": route.route_id,
            "route_label": route.route_label,
            "provider": route.provider,
            "model": route.model,
            "data_boundary": route.data_boundary,
            "destination_origin": destination_origin,
        }
        for node in nodes
    )


def _receipt_endpoint(route: ActiveModelRoute) -> str:
    """실제 전송 origin+path만 남기고 query·fragment·userinfo·token을 거부한다."""

    parsed = urlsplit(f"{route.endpoint.rstrip('/')}/v1/chat/completions")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Report Assistant receipt endpoint is invalid")
    hostname = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, "", ""))


def report_assistant_transfer_scopes(
    payload: dict[str, object],
    *,
    approved_new_analysis_artifact: bool = False,
) -> tuple[str, ...]:
    """실제 모델 payload의 존재 필드에서 사용자 공개 전송 범위를 결정한다."""

    scopes: set[str] = set()
    instruction = payload.get("instruction")
    if isinstance(instruction, str) and instruction:
        scopes.add("user_instruction")
    history = payload.get("history")
    if isinstance(history, list) and history:
        scopes.add("assistant_turn_history")
    report = payload.get("report")
    if isinstance(report, dict):
        scopes.add("report_metadata_layout")
        blocks = report.get("blocks")
        if isinstance(blocks, list) and blocks:
            scopes.add("report_block_content")
    artifacts = [payload.get("artifact")]
    additional = payload.get("additional_artifacts")
    if isinstance(additional, list):
        artifacts.extend(additional)
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        scopes.add("selected_artifact_metadata")
        if artifact.get("narrative"):
            scopes.add("selected_artifact_narrative")
        evidence = artifact.get("evidence")
        if isinstance(evidence, dict) and evidence.get("catalog"):
            scopes.add("selected_artifact_metrics")
        if artifact.get("chart_spec"):
            scopes.add("selected_artifact_chart_spec")
        if artifact.get("table_snapshot"):
            scopes.add("selected_artifact_table_snapshot")
    if payload.get("current_patch") is not None:
        scopes.add("pending_patch")
    if approved_new_analysis_artifact:
        scopes.add("approved_new_analysis_artifact")
    ordered = tuple(scope for scope in _SCOPE_ORDER if scope in scopes)
    if not ordered:
        raise ValueError("Report Assistant transfer scope is empty")
    return ordered


def report_assistant_public_report_context(
    definition: Any,
    artifacts: tuple[dict[str, Any], ...],
) -> dict[str, object]:
    """모델 payload와 동의 binding이 공유하는 현재 보고서 공개 정본을 만든다."""

    from app.services.report.layout import _paginate_layout

    aliases = {
        str(artifact["artifact_id"]): (
            "source_artifact" if index == 1 else f"source_artifact_{index}"
        )
        for index, artifact in enumerate(artifacts, start=1)
    }
    blocks = [
        {
            "block_id": block.block_id,
            "title": block.title,
            "type": block.type.value,
            "content": block.content,
            "artifact_ref": aliases.get(str(block.artifact_id)),
            "x": block.x,
            "y": block.y,
            "w": block.w,
            "h": block.h,
        }
        for block in definition.blocks
    ]
    page_count = len(
        _paginate_layout(
            [
                {
                    "block_id": block["block_id"],
                    "type": block["type"],
                    "x": block["x"],
                    "y": block["y"],
                    "w": block["w"],
                    "h": block["h"],
                }
                for block in blocks
            ],
            definition.orientation,
        )
    )
    return {
        "title": definition.title,
        "orientation": definition.orientation,
        "currency_display_unit": definition.currency_display_unit,
        "page_count": page_count,
        "blocks": blocks,
    }


def _session_source_binding(
    session: dict[str, Any], artifacts: tuple[dict[str, Any], ...]
) -> dict[str, object]:
    """동의 재사용 여부를 결정할 Report version·revision·Artifact checksum을 고정한다."""

    receipts = tuple(
        {
            "artifact_id": str(artifact["artifact_id"]),
            "artifact_checksum": str(artifact["artifact_checksum"]),
        }
        for artifact in artifacts
    )
    if not receipts or any(
        re.fullmatch(r"[0-9a-f]{64}", receipt["artifact_checksum"]) is None
        for receipt in receipts
    ):
        raise ValueError("Report Assistant Artifact binding is invalid")
    return {
        "assistant_request_id": str(session["assistant_request_id"]),
        "definition_id": str(session["session_definition_id"]),
        "definition_version": int(session["session_definition_version"]),
        "base_revision": int(session["base_revision"]),
        "report_draft_revision": int(session["report_draft_revision"]),
        "report_context_hash": str(session["report_context_hash"]),
        "artifacts": receipts,
    }


def _binding_hash(
    *,
    node: str,
    route: ActiveModelRoute,
    session: dict[str, Any],
    artifacts: tuple[dict[str, Any], ...],
    scopes: tuple[str, ...],
) -> str:
    """session source와 호출 node·route·policy·scope를 하나의 명시 동의에 결속한다."""

    return _canonical_sha256(
        {
            "policy_version": EXTERNAL_TRANSFER_POLICY_VERSION,
            "node": node,
            "route_fingerprint": route.route_fingerprint,
            "session": _session_source_binding(session, artifacts),
            "data_scopes": scopes,
        }
    )


async def _current_transfer_session(
    repository: Any,
    session: dict[str, Any],
    artifacts: tuple[dict[str, Any], ...],
    *,
    expected_report: object | None = None,
) -> dict[str, Any]:
    """현재 owner draft revision을 읽고 Assistant 시작 revision과 다르면 전송을 닫는다."""

    current_revision = await repository.get_draft_revision(
        str(session["session_definition_id"]),
        int(session["session_definition_version"]),
    )
    if int(current_revision) != int(session["base_revision"]):
        raise ValueError("Report Assistant report revision changed before transfer")
    definition = await repository.get_version(
        str(session["session_definition_id"]),
        int(session["session_definition_version"]),
    )
    if int(definition.draft_revision) != int(current_revision):
        raise ValueError("Report Assistant report context revision is inconsistent")
    report_context = report_assistant_public_report_context(definition, artifacts)
    report_context_hash = _canonical_sha256(report_context)
    if expected_report is not None:
        if not isinstance(expected_report, dict):
            raise ValueError("Report Assistant report context is invalid")
        if _canonical_sha256(expected_report) != report_context_hash:
            raise ValueError("Report Assistant report payload changed before transfer")
    return {
        **session,
        "report_draft_revision": int(current_revision),
        "report_context_hash": report_context_hash,
    }


def _disclosure_response(row: dict[str, object]) -> ReportAssistantExternalTransferDisclosureResponse:
    """저장된 서버 공개문을 public typed 응답으로 복원한다."""

    route = _json_object(row["route_json"], "Report Assistant route disclosure")
    return ReportAssistantExternalTransferDisclosureResponse.model_validate(
        {
            "disclosure_id": row["disclosure_id"],
            "assistant_request_id": row["assistant_request_id"],
            "policy_version": row["policy_version"],
            "provider_routes": route.get("provider_routes"),
            "data_scopes": _json_sequence(row["data_scopes_json"], "data scopes"),
            "excluded_data": _json_sequence(row["excluded_data_json"], "excluded data"),
            "content_warning": row["content_warning"],
            "disclosure_hash": row["disclosure_hash"],
            "expires_at": row["expires_at"],
            "consent_required": True,
        }
    )


@dataclass(frozen=True)
class ReportAssistantTransferAuthorization:
    """preflight 이후 각 transport attempt가 소비할 불변 동의 결속이다."""

    assistant_request_id: str
    policy_version: str
    node: str
    route: ActiveModelRoute
    binding_hash: str
    data_scopes: tuple[str, ...]
    scope_hash: str
    disclosure_id: str | None
    consent_id: str | None

    async def record_attempt(
        self,
        repository: Any,
        *,
        attempt: int,
        payload_hash: str,
        model_execution_id: str,
        minimum_lease_seconds: int,
    ) -> str:
        """현재 결속과 payload hash를 transport 전에 별도 transaction으로 커밋한다."""

        if not 1 <= attempt <= 4:
            raise ValueError("Report Assistant model attempt is outside the receipt contract")
        if len(payload_hash) != 64 or any(
            character not in "0123456789abcdef" for character in payload_hash
        ):
            raise ValueError("Report Assistant payload hash is invalid")
        if re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            model_execution_id,
        ) is None:
            raise ValueError("Report Assistant model execution token is invalid")
        if (
            isinstance(minimum_lease_seconds, bool)
            or not isinstance(minimum_lease_seconds, int)
            or not 1 <= minimum_lease_seconds <= 3600
        ):
            raise ValueError("Report Assistant minimum execution lease is invalid")
        current_session = await repository.get_assistant_session(
            self.assistant_request_id
        )
        current_artifacts = tuple(
            await repository.get_assistant_artifacts(self.assistant_request_id)
        )
        result_artifact_id = current_session.get("result_artifact_id")
        if result_artifact_id is not None and all(
            str(artifact["artifact_id"]) != str(result_artifact_id)
            for artifact in current_artifacts
        ):
            current_artifacts = (
                *current_artifacts,
                await repository.get_assistant_artifact(str(result_artifact_id)),
            )
        current_session = await _current_transfer_session(
            repository, current_session, current_artifacts
        )
        current_binding_hash = _binding_hash(
            node=self.node,
            route=self.route,
            session=current_session,
            artifacts=current_artifacts,
            scopes=self.data_scopes,
        )
        if current_binding_hash != self.binding_hash:
            raise ValueError(
                "Report Assistant transfer binding changed before transport"
            )
        try:
            return await repository.insert_assistant_transfer_receipt(
                self.assistant_request_id,
                disclosure_id=self.disclosure_id,
                consent_id=self.consent_id,
                policy_version=self.policy_version,
                node=self.node,
                attempt=attempt,
                data_boundary=self.route.data_boundary,
                manifest_version=self.route.manifest_version,
                route_id=self.route.route_id,
                provider=self.route.provider,
                model=self.route.model,
                model_snapshot=self.route.capacity.snapshot,
                endpoint=_receipt_endpoint(self.route),
                route_fingerprint=self.route.route_fingerprint,
                binding_hash=self.binding_hash,
                data_scopes=self.data_scopes,
                scope_hash=self.scope_hash,
                payload_hash=payload_hash,
                model_execution_id=model_execution_id,
                minimum_lease_seconds=minimum_lease_seconds,
            )
        except KeyError as error:
            raise ValueError("ASSISTANT_MODEL_EXECUTION_CONFLICT") from error


async def authorize_report_assistant_transfer(
    repository: Any,
    *,
    assistant_request_id: str,
    node: str,
    payload: dict[str, object],
    session: dict[str, Any],
    artifacts: tuple[dict[str, Any], ...],
    approved_new_analysis_artifact: bool = False,
) -> ReportAssistantTransferAuthorization:
    """manifest boundary와 현재 세션 결속을 검증하고 외부 route는 명시 동의를 요구한다."""

    route = active_route_for_node(resolve_active_model_routes(), node)
    session = await _current_transfer_session(
        repository,
        session,
        artifacts,
        expected_report=payload.get("report"),
    )
    scopes = report_assistant_transfer_scopes(
        payload,
        approved_new_analysis_artifact=approved_new_analysis_artifact,
    )
    scope_hash = _canonical_sha256(scopes)
    binding_hash = _binding_hash(
        node=node,
        route=route,
        session=session,
        artifacts=artifacts,
        scopes=scopes,
    )
    # internal label만 바꾼 임의 HTTPS route가 동의 없이 활성화되지 않도록
    # consent 분기보다 먼저 manifest 승인 origin을 독립 재검증한다.
    provider_routes = _public_provider_routes(route)
    if route.data_boundary == "internal":
        return ReportAssistantTransferAuthorization(
            assistant_request_id=assistant_request_id,
            policy_version=EXTERNAL_TRANSFER_POLICY_VERSION,
            node=node,
            route=route,
            binding_hash=binding_hash,
            data_scopes=scopes,
            scope_hash=scope_hash,
            disclosure_id=None,
            consent_id=None,
        )
    if route.data_boundary != "external":
        raise ValueError("Report Assistant model route data boundary is invalid")
    consent = await repository.find_assistant_external_consent(
        assistant_request_id, binding_hash
    )
    if consent is not None:
        if (
            str(consent["policy_version"]) != EXTERNAL_TRANSFER_POLICY_VERSION
            or str(consent["route_fingerprint"]) != route.route_fingerprint
            or str(consent["scope_hash"]) != scope_hash
            or str(consent["binding_hash"]) != binding_hash
        ):
            raise ValueError("Report Assistant external consent binding is invalid")
        return ReportAssistantTransferAuthorization(
            assistant_request_id=assistant_request_id,
            policy_version=EXTERNAL_TRANSFER_POLICY_VERSION,
            node=node,
            route=route,
            binding_hash=binding_hash,
            data_scopes=scopes,
            scope_hash=scope_hash,
            disclosure_id=str(consent["disclosure_id"]),
            consent_id=str(consent["consent_id"]),
        )

    disclosure_id = str(uuid4())
    deployment_preapproved = _deployment_preapproval_enabled()
    route_json = {
        "manifest_version": route.manifest_version,
        "provider_routes": provider_routes,
        "report_draft_revision": session["report_draft_revision"],
        "report_context_hash": session["report_context_hash"],
        "authorization_mode": (
            "deployment_preapproval" if deployment_preapproved else "interactive_consent"
        ),
    }
    expires_at = datetime.now(timezone.utc) + _DISCLOSURE_LIFETIME
    disclosure_hash = _canonical_sha256(
        {
            "disclosure_id": disclosure_id,
            "assistant_request_id": assistant_request_id,
            "policy_version": EXTERNAL_TRANSFER_POLICY_VERSION,
            "route": route_json,
            "route_fingerprint": route.route_fingerprint,
            "binding_hash": binding_hash,
            "data_scopes": scopes,
            "scope_hash": scope_hash,
            "excluded_data": _EXCLUDED_DATA,
            "content_warning": _CONTENT_WARNING,
            "expires_at": expires_at.isoformat(),
        }
    )
    row = await repository.create_assistant_transfer_disclosure(
        assistant_request_id,
        disclosure_id=disclosure_id,
        policy_version=EXTERNAL_TRANSFER_POLICY_VERSION,
        node=node,
        route=route_json,
        route_fingerprint=route.route_fingerprint,
        binding_hash=binding_hash,
        data_scopes=scopes,
        scope_hash=scope_hash,
        excluded_data=_EXCLUDED_DATA,
        content_warning=_CONTENT_WARNING,
        disclosure_hash=disclosure_hash,
        expires_at=expires_at,
    )
    disclosure = _disclosure_response(row)
    if not deployment_preapproved:
        raise ExternalTransferConsentRequired(disclosure)
    consent = await repository.accept_assistant_external_transfer(
        assistant_request_id,
        str(disclosure.disclosure_id),
        disclosure.disclosure_hash,
    )
    return ReportAssistantTransferAuthorization(
        assistant_request_id=assistant_request_id,
        policy_version=EXTERNAL_TRANSFER_POLICY_VERSION,
        node=node,
        route=route,
        binding_hash=binding_hash,
        data_scopes=scopes,
        scope_hash=scope_hash,
        disclosure_id=str(consent["disclosure_id"]),
        consent_id=str(consent["consent_id"]),
    )


async def accept_report_assistant_external_transfer(
    repository: Any,
    *,
    assistant_request_id: str,
    disclosure_id: str,
    disclosure_hash: str,
    session: dict[str, Any],
    artifacts: tuple[dict[str, Any], ...],
) -> ReportAssistantExternalTransferConsentResponse:
    """공개문이 현재 manifest·session·Artifact·scope와 같을 때만 명시 동의를 저장한다."""

    disclosure = await repository.get_assistant_transfer_disclosure(
        assistant_request_id, disclosure_id
    )
    if str(disclosure["disclosure_hash"]) != disclosure_hash:
        raise ValueError("외부 전송 공개문이 변경되었습니다.")
    if _utc_datetime(disclosure["expires_at"], "disclosure expiry") <= datetime.now(
        timezone.utc
    ):
        raise ValueError("외부 전송 공개문의 유효 시간이 지났습니다.")
    route_json = _json_object(disclosure["route_json"], "Report Assistant route disclosure")
    routes = route_json.get("provider_routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("외부 전송 route 공개문이 올바르지 않습니다.")
    node = str(disclosure["node"])
    session = await _current_transfer_session(repository, session, artifacts)
    report_context_hash = str(route_json.get("report_context_hash") or "")
    if (
        re.fullmatch(r"[0-9a-f]{64}", report_context_hash) is None
        or route_json.get("report_draft_revision") != session["report_draft_revision"]
        or report_context_hash != session["report_context_hash"]
    ):
        raise ValueError("외부 전송 공개문의 보고서 revision이 변경되었습니다.")
    route = active_route_for_node(resolve_active_model_routes(), node)
    if route.data_boundary != "external":
        raise ValueError("외부 전송 동의가 필요하지 않은 route입니다.")
    scopes = _json_sequence(disclosure["data_scopes_json"], "data scopes")
    binding_hash = _binding_hash(
        node=node,
        route=route,
        session=session,
        artifacts=artifacts,
        scopes=scopes,
    )
    expected_routes = _public_provider_routes(route)
    if (
        str(disclosure["policy_version"]) != EXTERNAL_TRANSFER_POLICY_VERSION
        or str(disclosure["route_fingerprint"]) != route.route_fingerprint
        or str(disclosure["binding_hash"]) != binding_hash
        or str(disclosure["scope_hash"]) != _canonical_sha256(scopes)
        or routes != list(expected_routes)
    ):
        raise ValueError("외부 전송 공개문이 현재 실행 경계와 일치하지 않습니다.")
    consent = await repository.accept_assistant_external_transfer(
        assistant_request_id, disclosure_id, disclosure_hash
    )
    return ReportAssistantExternalTransferConsentResponse.model_validate(
        {
            "consent_id": consent["consent_id"],
            "assistant_request_id": consent["assistant_request_id"],
            "policy_version": consent["policy_version"],
            "provider_routes": expected_routes,
            "data_scopes": scopes,
            "consented_at": consent["consented_at"],
        }
    )


async def latest_report_assistant_transfer_disclosure(
    repository: Any, assistant_request_id: str
) -> ReportAssistantExternalTransferDisclosureResponse:
    """새로고침 복구를 위해 현재 owner 세션의 최신 미만료 공개문을 반환한다."""

    row = await repository.get_latest_assistant_transfer_disclosure(
        assistant_request_id
    )
    return _disclosure_response(row)
