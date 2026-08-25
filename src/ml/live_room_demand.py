from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

FEATURES = ["horizon_days", "available_room_nights", "booking_on_hand", "booking_on_hand_ratio",
            "rooms_sold_lag_1", "rooms_sold_lag_7", "rooms_sold_lag_14", "rooms_sold_mean_7",
            "rooms_sold_mean_28", "cancellation_rate_28", "target_day_of_week", "target_month",
            "target_is_weekend", "target_is_month_start", "target_is_month_end",
            "target_is_public_holiday", "room_type_code", "target_season_code"]
CATEGORICAL = ["room_type_code", "target_season_code"]


class TrinoClient:
    """HTTPS Trino statement protocol을 비동기로 호출하고 same-origin page만 추적한다."""

    def __init__(self) -> None:
        self.url = os.environ["TRINO_URL"].rstrip("/")
        self.user = os.environ["TRINO_RUNTIME_USER"]
        password = os.environ["TRINO_RUNTIME_PASSWORD"]
        ca_file = os.environ.get("TRINO_TLS_CA_FILE")
        endpoint = httpx.URL(self.url)
        if endpoint.scheme != "https" or not endpoint.host or endpoint.query or endpoint.fragment:
            raise ValueError("TRINO_URL must be one HTTPS origin")
        if not ca_file:
            raise ValueError("TRINO_TLS_CA_FILE is required")
        self.origin = (endpoint.scheme, endpoint.host.casefold(), endpoint.port or 443)
        self.headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "X-Trino-User": self.user,
            "X-Trino-Catalog": "pms",
            "X-Trino-Schema": "walkerhill_v4_3",
        }
        self.client = httpx.AsyncClient(
            auth=httpx.BasicAuth(self.user, password),
            verify=ca_file,
            trust_env=False,
            timeout=60,
        )

    async def query(self, sql: str) -> pd.DataFrame:
        """읽기 SQL을 실행하고 terminal page까지 최대 100회 수집한다."""

        response = await self.client.post(
            f"{self.url}/v1/statement",
            content=sql.encode("utf-8"),
            headers=self.headers,
        )
        response.raise_for_status()
        payload = response.json()
        query_id = str(payload.get("id") or "")
        columns: list[str] = []
        rows: list[list[Any]] = []
        for _ in range(100):
            if payload.get("error"):
                raise RuntimeError(payload["error"].get("message", "Trino query failed"))
            if payload.get("columns"):
                columns = [item["name"] for item in payload["columns"]]
            rows.extend(payload.get("data", []))
            if payload.get("stats", {}).get("state") == "FINISHED":
                frame = pd.DataFrame(rows, columns=columns)
                if query_id:
                    frame.attrs["trino_query_id"] = query_id
                return frame
            next_uri = payload.get("nextUri")
            if not isinstance(next_uri, str):
                raise RuntimeError("Trino response ended before terminal state")
            uri = httpx.URL(next_uri)
            origin = (uri.scheme, uri.host.casefold() if uri.host else "", uri.port or 443)
            if origin != self.origin:
                raise RuntimeError("Trino nextUri changed coordinator origin")
            response = await self.client.get(next_uri, headers=self.headers)
            response.raise_for_status()
            payload = response.json()
        raise RuntimeError("Trino query exceeded page limit")

    async def aclose(self) -> None:
        """소유한 HTTP connection pool을 닫는다."""

        await self.client.aclose()


@dataclass(frozen=True)
class ForecastRequest:
    property_id: str
    feature_as_of: date

    @classmethod
    def create(cls, property_id: str, feature_as_of: str) -> "ForecastRequest":
        if not re.fullmatch(r"[A-Z0-9_]+", property_id):
            raise ValueError("property_id must contain only A-Z, 0-9, and underscore")
        return cls(property_id, date.fromisoformat(feature_as_of[:10]))


class LiveRoomDemandService:
    def __init__(self, client: TrinoClient | None = None) -> None:
        self.client = client or TrinoClient()

    async def health(self) -> None:
        """runtime principal의 실제 statement 권한을 확인한다."""

        await self.client.query("SELECT 1 AS ready")

    async def _load(self, request: ForecastRequest) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        start, end, hotel = request.feature_as_of - timedelta(days=760), request.feature_as_of + timedelta(days=7), request.property_id
        inventory, calendar, reservations = await asyncio.gather(
            self.client.query(
                f"SELECT hotel_code, business_date, room_type_code, available_room_nights FROM pms.walkerhill_v4_3.pms_room_inventory_daily "
                f"WHERE hotel_code = '{hotel}' AND business_date BETWEEN DATE '{start}' AND DATE '{end}'"),
            self.client.query(
                f"SELECT business_date, day_of_week, is_weekend, is_holiday, season_code FROM pms.walkerhill_v4_3.calendar_daily "
                f"WHERE business_date BETWEEN DATE '{start}' AND DATE '{end}'"),
            self.client.query(
                f"SELECT room_type_code, booked_at, checkin_date, cancelled_at, reservation_status FROM pms.walkerhill_v4_3.pms_reservations "
                f"WHERE hotel_code = '{hotel}' AND checkin_date BETWEEN DATE '{start}' AND DATE '{end}'"),
        )
        if inventory.empty or calendar.empty or reservations.empty:
            raise ValueError(f"live PMS data not found for property_id={hotel}")
        return inventory, calendar, reservations

    async def aclose(self) -> None:
        """Trino client connection pool을 닫는다."""

        await self.client.aclose()

    def _build_features(self, request: ForecastRequest, inventory: pd.DataFrame,
                        calendar: pd.DataFrame, reservations: pd.DataFrame) -> pd.DataFrame:
        for frame, column in ((inventory, "business_date"), (calendar, "business_date"), (reservations, "checkin_date")):
            frame[column] = pd.to_datetime(frame[column]).dt.date
        reservations["booked_date"] = pd.to_datetime(reservations["booked_at"], utc=True).dt.date
        reservations["cancelled_date"] = pd.to_datetime(reservations["cancelled_at"], utc=True, errors="coerce").dt.date
        calendar_map = calendar.set_index("business_date").to_dict(orient="index")
        reservation_groups = {key: group for key, group in reservations.groupby(["checkin_date", "room_type_code"])}
        sold = reservations[reservations["reservation_status"] == "CHECKED_OUT"].groupby(
            ["checkin_date", "room_type_code"]).size().to_dict()
        reservation_totals = reservations.groupby(["checkin_date", "room_type_code"]).size().to_dict()
        cancellation_totals = reservations[reservations["reservation_status"] == "CANCELLED"].groupby(
            ["checkin_date", "room_type_code"]).size().to_dict()
        rows: list[dict[str, Any]] = []
        first_training = request.feature_as_of - timedelta(days=540)
        for item in inventory.sort_values(["business_date", "room_type_code"]).itertuples(index=False):
            target, is_training = item.business_date, item.business_date <= request.feature_as_of
            if (is_training and target < first_training) or (not is_training and target > request.feature_as_of + timedelta(days=7)):
                continue
            horizons = range(1, 8) if is_training else [(target - request.feature_as_of).days]
            group = reservation_groups.get((target, item.room_type_code), pd.DataFrame())
            for horizon in horizons:
                cutoff = target - timedelta(days=horizon)
                if cutoff > request.feature_as_of:
                    continue
                if group.empty:
                    booking_on_hand = 0
                else:
                    active = (group["booked_date"] <= cutoff) & (group["cancelled_date"].isna() | (group["cancelled_date"] > cutoff))
                    booking_on_hand = int(active.sum())
                history = [sold.get((cutoff - timedelta(days=n), item.room_type_code), 0) for n in range(1, 29)]
                window_total = sum(reservation_totals.get((cutoff - timedelta(days=n), item.room_type_code), 0)
                                   for n in range(28))
                window_cancelled = sum(cancellation_totals.get((cutoff - timedelta(days=n), item.room_type_code), 0)
                                       for n in range(28))
                cancellation_rate = window_cancelled / window_total if window_total else 0.0
                cal, available = calendar_map[target], int(item.available_room_nights)
                rows.append({"property_id": item.hotel_code, "target_date": target, "room_type_code": item.room_type_code,
                             "horizon_days": horizon, "available_room_nights": available,
                             "booking_on_hand": booking_on_hand,
                             "booking_on_hand_ratio": booking_on_hand / available if available else 0.0,
                             "rooms_sold_lag_1": history[0], "rooms_sold_lag_7": history[6],
                             "rooms_sold_lag_14": history[13], "rooms_sold_mean_7": float(np.mean(history[:7])),
                             "rooms_sold_mean_28": float(np.mean(history)), "cancellation_rate_28": cancellation_rate,
                             "seasonal_naive_rooms_sold": sold.get((target - timedelta(days=7), item.room_type_code), 0),
                             "target_day_of_week": int(cal["day_of_week"]), "target_month": target.month,
                             "target_is_weekend": int(cal["is_weekend"]), "target_is_month_start": int(target.day == 1),
                             "target_is_month_end": int((target + timedelta(days=1)).month != target.month),
                             "target_is_public_holiday": int(cal["is_holiday"]), "target_season_code": cal["season_code"],
                             "is_training": is_training,
                             "rooms_sold": sold.get((target, item.room_type_code), 0) if is_training else np.nan})
        return pd.DataFrame(rows)

    @staticmethod
    def _model() -> Pipeline:
        numeric = [column for column in FEATURES if column not in CATEGORICAL]
        transform = ColumnTransformer([("numeric", "passthrough", numeric),
                                       ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL)])
        return Pipeline([("features", transform),
                         ("model", HistGradientBoostingRegressor(max_iter=150, learning_rate=0.08, random_state=20260819))])
