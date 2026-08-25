"""자연어 ML 요청을 승인 Runtime 실행과 검증된 화면 계약으로 통합한다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ml_prediction_client import (
    MLPredictionClient,
    MLPredictionRejected,
    MLPredictionUnavailable,
)
from app.authorization import has_capability
from app.contracts import Capability, RequestContext
from app.services.mcp_access_policy import is_ml_allowed


@dataclass(frozen=True)
class MLAnalysisError(Exception):
    """공개 가능한 ML 오류 계약이다."""

    status_code: int
    code: str
    message: str
    retryable: bool = False
    required_action: str = "NONE"


class MLPredictionService:
    """ML 요청의 권한, Runtime 실행, 검증, 집계와 감사를 한 경계에서 처리한다."""

    def __init__(self, client: MLPredictionClient) -> None:
        self._client = client

    async def predict_from_query(
        self,
        query: str,
        context: RequestContext,
        session: AsyncSession,
        conversation_id: UUID | None = None,
        expected_head_turn_id: UUID | None = None,
        approved_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """질의 또는 승인 scope를 검증해 live PMS 예측을 실행하고 근거와 감사를 남긴다."""

        events = ["ML_REQUESTED"]
        normalized: dict[str, Any] = {}
        response: dict[str, Any] = {}
        try:
            if not is_ml_allowed(
                role=context.role,
                capability_allowed=has_capability(
                    context.role, Capability.RUN_ANALYSIS
                ),
            ):
                raise MLAnalysisError(403, "ML_ACCESS_DENIED", "해당 데이터에 대한 접근 권한이 없어 예측을 실행하지 않았습니다.")
            events.append("ML_AUTHORIZED")
            if approved_request is None:
                previous_hotel = await self._conversation_hotel(
                    session, conversation_id, expected_head_turn_id, context.user_id
                )
                normalized = self._normalize(query, previous_hotel)
            else:
                normalized = self._normalize_approved_request(approved_request)
            capability = await self._client.capability(context.trace_id)
            self._validate_capability(normalized, capability)
            events.extend(["ML_FEATURE_QUERY_STARTED", "ML_PREDICTION_STARTED"])
            request = {
                "metric": normalized["metric"],
                "hotel_scope": normalized["hotel_scope"],
                "horizon": normalized["horizon"],
                "as_of": capability["feature_as_of"],
            }
            try:
                result = await self._client.predict(request, context.trace_id, str(context.request_id))
            except MLPredictionRejected as error:
                raise MLAnalysisError(422, "ML_CAPABILITY_NOT_FOUND", str(error), False, "CHANGE_HOTEL_SCOPE") from error
            except MLPredictionUnavailable as error:
                raise MLAnalysisError(503, "ML_RUNTIME_UNAVAILABLE", str(error), True, "RETRY") from error
            events.extend(["ML_FEATURE_QUERY_SUCCEEDED", "ML_PREDICTION_SUCCEEDED"])
            daily, room_types = self._validate_and_aggregate(result, request)
            events.append("ML_VALIDATION_SUCCEEDED")
            response = self._response(context, request, capability, result, daily, room_types)
            events.append("ML_RESPONSE_RETURNED")
            await self._save_audit(session, context, conversation_id, events, request, response)
            return response
        except MLAnalysisError as error:
            events.append(self._failure_event(error.code))
            await self._save_audit(
                session,
                context,
                conversation_id,
                events,
                normalized,
                {"error": {"code": error.code, "message": error.message}},
            )
            raise
        except (MLPredictionUnavailable, ValueError) as error:
            failure = MLAnalysisError(503, "ML_RUNTIME_UNAVAILABLE", str(error), True, "RETRY")
            events.append("ML_CAPABILITY_FAILED")
            await self._save_audit(
                session,
                context,
                conversation_id,
                events,
                normalized,
                {"error": {"code": failure.code, "message": failure.message}},
            )
            raise failure from error

    async def predict_approved_task(
        self,
        request: dict[str, Any],
        context: RequestContext,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """typed MCP 예측 scope를 동일한 권한·모델 검증 경로로 실행한다."""
        return await self.predict_from_query(
            "", context, session, approved_request=request
        )

    @staticmethod
    def _normalize_approved_request(request: dict[str, Any]) -> dict[str, Any]:
        hotel_scope = str(request.get("hotel_scope") or "").strip().upper()
        metric = str(request.get("metric") or "").strip().upper()
        horizon = request.get("horizon")
        if not re.fullmatch(r"[A-Z0-9_]{1,32}", hotel_scope):
            raise MLAnalysisError(
                422, "ML_HOTEL_REQUIRED", "An approved hotel code is required."
            )
        if metric != "OCCUPANCY_RATE":
            raise MLAnalysisError(
                422, "ML_CAPABILITY_NOT_FOUND", "The ML metric is not approved."
            )
        if (
            not isinstance(horizon, int)
            or isinstance(horizon, bool)
            or not 1 <= horizon <= 7
        ):
            raise MLAnalysisError(
                422, "ML_HORIZON_INVALID", "The approved horizon is 1 to 7 days."
            )
        return {
            "intent": "ML_FORECAST",
            "hotel_scope": hotel_scope,
            "metric": metric,
            "horizon": horizon,
        }

    @staticmethod
    def _normalize(query: str, previous_hotel: str | None) -> dict[str, Any]:
        upper = query.upper()
        candidates = re.findall(r"\b[A-Z][A-Z0-9_]{2,31}\b", upper)
        ignored = {"ML", "PMS", "OCCUPANCY_RATE"}
        hotel = next((item for item in candidates if item not in ignored), None)
        if hotel is None and re.match(r"^\s*\d+\s*일만", query):
            hotel = previous_hotel
        if not hotel:
            raise MLAnalysisError(
                422,
                "ML_HOTEL_REQUIRED",
                "예측할 호텔 코드가 필요합니다. 승인된 모델의 호텔 코드를 입력해 주세요.",
                False,
                "PROVIDE_HOTEL_SCOPE",
            )
        match = re.search(r"(\d+)\s*일", query)
        horizon = (
            int(match.group(1))
            if match
            else 1
            if re.search(r"내일", query)
            else 7
            if re.search(r"(이번|다음)\s*주", query)
            else 0
        )
        if not 1 <= horizon <= 7:
            raise MLAnalysisError(422, "ML_HORIZON_INVALID", "현재 예측 가능한 기간은 1~7일입니다.", False, "CHANGE_HORIZON")
        return {"intent": "ML_FORECAST", "hotel_scope": hotel, "metric": "OCCUPANCY_RATE", "horizon": horizon}

    @staticmethod
    async def _conversation_hotel(
        session: AsyncSession,
        conversation_id: UUID | None,
        expected_head_turn_id: UUID | None,
        user_id: UUID,
    ) -> str | None:
        if conversation_id is None:
            return None
        conversation = (
            await session.execute(
                text(
                    """
                    SELECT head_turn_id
                    FROM chat.conversations
                    WHERE conversation_id = :conversation_id AND owner_user_id = :user_id
                    """
                ),
                {"conversation_id": conversation_id, "user_id": user_id},
            )
        ).mappings().first()
        if conversation is None:
            raise MLAnalysisError(404, "CONVERSATION_NOT_FOUND", "대화 Context를 찾을 수 없습니다.", False, "CREATE_CONVERSATION")
        if expected_head_turn_id is not None and conversation["head_turn_id"] != expected_head_turn_id:
            raise MLAnalysisError(409, "CONVERSATION_CONFLICT", "대화가 갱신되어 요청을 다시 확인해야 합니다.", True, "RETRY")
        return await session.scalar(
            text(
                """
                SELECT details_json_redacted -> 'request' ->> 'hotel_scope'
                FROM governance.audit_events
                WHERE actor_user_id = :user_id
                  AND action_code = 'ML_RESPONSE_RETURNED'
                  AND details_json_redacted ->> 'conversation_id' = :conversation_id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id, "conversation_id": str(conversation_id)},
        )

    @staticmethod
    def _validate_capability(request: dict[str, Any], capability: dict[str, Any]) -> None:
        if request["hotel_scope"] != capability.get("property_id"):
            raise MLAnalysisError(
                422,
                "ML_CAPABILITY_NOT_FOUND",
                f"{request['hotel_scope']}용 승인 모델이 없어 예측을 실행하지 않았습니다. 현재 예측 가능한 호텔은 {capability.get('property_id')}입니다.",
                False,
                "CHANGE_HOTEL_SCOPE",
            )
        if request["metric"] != capability.get("metric") or request["horizon"] > int(capability.get("max_horizon", 0)):
            raise MLAnalysisError(422, "ML_HORIZON_INVALID", "현재 예측 가능한 기간은 1~7일입니다.", False, "CHANGE_HORIZON")
        if capability.get("status") != "READY" or capability.get("feature_source") != "LIVE_TRINO_PMS":
            raise MLAnalysisError(503, "ML_CAPABILITY_NOT_READY", "승인된 실제 PMS 예측 모델을 사용할 수 없습니다.", True, "RETRY")

    @staticmethod
    def _validate_and_aggregate(
        result: dict[str, Any], request: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = result.get("predictions")
        if (
            not isinstance(rows, list)
            or not rows
            or result.get("property_id") != request["hotel_scope"]
            or result.get("metric") != request["metric"]
            or result.get("feature_as_of") != request["as_of"]
        ):
            raise MLAnalysisError(502, "ML_PREDICTION_INVALID", "예측 결과 검증을 통과하지 못해 결과를 표시하지 않았습니다.", True, "RETRY")
        start = date.fromisoformat(request["as_of"]) + timedelta(days=1)
        end = start + timedelta(days=request["horizon"])
        daily: dict[str, dict[str, Any]] = {}
        details: list[dict[str, Any]] = []
        for row in rows:
            try:
                target = date.fromisoformat(str(row["target_date"]))
                available = float(row["available_room_nights"])
                booked = float(row["booking_on_hand"])
                predicted = float(row["predicted_rooms_sold"])
                occupancy = float(row["predicted_occupancy_rate"])
            except (KeyError, TypeError, ValueError) as error:
                raise MLAnalysisError(502, "ML_PREDICTION_INVALID", "예측 결과 검증을 통과하지 못해 결과를 표시하지 않았습니다.", True, "RETRY") from error
            if not start <= target < end or available < 0 or booked < 0 or not 0 <= predicted <= available or not 0 <= occupancy <= 1:
                raise MLAnalysisError(502, "ML_PREDICTION_INVALID", "예측 결과 검증을 통과하지 못해 결과를 표시하지 않았습니다.", True, "RETRY")
            item = daily.setdefault(str(target), {"target_date": str(target), "available_rooms": 0.0, "booking_on_hand": 0.0, "predicted_rooms_sold": 0.0})
            item["available_rooms"] += available
            item["booking_on_hand"] += booked
            item["predicted_rooms_sold"] += predicted
            details.append(dict(row))
        if len(daily) != request["horizon"]:
            raise MLAnalysisError(502, "ML_PREDICTION_INVALID", "예측 날짜 수가 요청 기간과 일치하지 않습니다.", True, "RETRY")
        values = sorted(daily.values(), key=lambda item: item["target_date"])
        for item in values:
            item["remaining_rooms"] = max(0.0, item["available_rooms"] - item["predicted_rooms_sold"])
            item["predicted_occupancy_rate"] = item["predicted_rooms_sold"] / item["available_rooms"] if item["available_rooms"] else 0.0
        return values, details

    @staticmethod
    def _response(
        context: RequestContext,
        request: dict[str, Any],
        capability: dict[str, Any],
        result: dict[str, Any],
        daily: list[dict[str, Any]],
        room_types: list[dict[str, Any]],
    ) -> dict[str, Any]:
        available = sum(item["available_rooms"] for item in daily)
        predicted = sum(item["predicted_rooms_sold"] for item in daily)
        changes = [
            (daily[index - 1], daily[index], daily[index]["predicted_rooms_sold"] - daily[index - 1]["predicted_rooms_sold"])
            for index in range(1, len(daily))
        ]
        largest = max(changes, key=lambda item: abs(item[2]), default=None)
        trend = (
            f"{largest[0]['target_date']} 대비 {largest[1]['target_date']} 예측 판매량이 {abs(largest[2]):.1f}개 {'증가' if largest[2] >= 0 else '감소'}하는 패턴이 확인됩니다."
            if largest else "비교할 날짜가 부족해 변화 패턴을 설명하지 않습니다."
        )
        return {
            "status": "SUCCESS",
            "request_id": str(context.request_id),
            "trace_id": context.trace_id,
            "request": {**request, "as_of": capability["feature_as_of"]},
            "summary": {
                "total_available_room_nights": available,
                "predicted_sold_room_nights": predicted,
                "remaining_room_nights": max(0.0, available - predicted),
                "daily_average_predicted_rooms": predicted / len(daily),
                "weighted_occupancy_rate": predicted / available if available else 0.0,
            },
            "daily": daily,
            "room_type_details": room_types,
            "trend": {"description": trend, "cause_analysis_available": False},
            "limitations": ["프로모션·행사·외부 이벤트 데이터는 현재 분석 범위에 포함되지 않습니다."],
            "evidence": {
                "authorization": "PASSED",
                "capability": "APPROVED",
                "model_name": result.get("model_name"),
                "model_version": result.get("model_version"),
                "artifact_hash": result.get("artifact_hash"),
                "feature_source": result.get("feature_source"),
                "training_source": result.get("training_source") or result.get("feature_source"),
                "feature_as_of": result.get("feature_as_of"),
                "prediction_rows": len(room_types),
                "execution_id": result.get("execution_id") or str(uuid4()),
                "trino_query_ids": result.get("trino_query_ids") or [],
                "strategy": result.get("selected_strategy"),
                "rag_called": False,
            },
        }

    @staticmethod
    def _failure_event(code: str) -> str:
        if code == "ML_ACCESS_DENIED":
            return "ML_AUTHORIZATION_FAILED"
        if code in {"ML_CAPABILITY_NOT_FOUND", "ML_CAPABILITY_NOT_READY", "ML_HORIZON_INVALID", "ML_HOTEL_REQUIRED"}:
            return "ML_CAPABILITY_FAILED"
        if code == "ML_PREDICTION_INVALID":
            return "ML_VALIDATION_FAILED"
        return "ML_PREDICTION_FAILED"

    @staticmethod
    async def _save_audit(
        session: AsyncSession,
        context: RequestContext,
        conversation_id: UUID | None,
        events: list[str],
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        details = {
            "request_id": str(context.request_id),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "request": request,
            "summary": response.get("summary"),
            "evidence": response.get("evidence"),
            "error": response.get("error"),
            "rag_called": False,
        }
        await session.execute(
            text(
                """
                INSERT INTO governance.audit_events
                    (audit_event_id, request_id, actor_user_id, actor_role, action_code,
                     object_type, object_id, details_json_redacted, trace_id, created_at)
                VALUES
                    (:audit_event_id, :request_id, :actor_user_id, :actor_role, :action_code,
                     'ML_MODEL', :object_id, CAST(:details AS jsonb), :trace_id, now())
                """
            ),
            [
                {
                    "audit_event_id": uuid4(),
                    "request_id": None,
                    "actor_user_id": context.user_id,
                    "actor_role": context.role.value,
                    "action_code": event,
                    "object_id": str(response.get("evidence", {}).get("model_version") or request.get("hotel_scope") or "unknown"),
                    "details": json.dumps(details, ensure_ascii=False, sort_keys=True),
                    "trace_id": context.trace_id,
                }
                for event in events
            ],
        )
        await session.commit()
