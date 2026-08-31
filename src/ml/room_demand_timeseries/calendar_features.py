"""예측일에 미리 알려진 한국 휴일·외생 달력 feature만 결합한다."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


_MOVABLE_HOLIDAYS = """
2017-01-27 2017-01-28 2017-01-29 2017-01-30 2017-10-04 2017-10-05 2017-10-06
2018-02-15 2018-02-16 2018-02-17 2018-05-22 2018-09-23 2018-09-24 2018-09-25
2019-02-04 2019-02-05 2019-02-06 2019-05-12 2019-09-12 2019-09-13 2019-09-14
2020-01-24 2020-01-25 2020-01-26 2020-01-27 2020-04-30 2020-09-30 2020-10-01 2020-10-02
2021-02-11 2021-02-12 2021-02-13 2021-05-19 2021-09-20 2021-09-21 2021-09-22
2022-01-31 2022-02-01 2022-02-02 2022-05-08 2022-09-09 2022-09-10 2022-09-11 2022-09-12
2023-01-21 2023-01-22 2023-01-23 2023-01-24 2023-05-27 2023-09-28 2023-09-29 2023-09-30 2023-10-01 2023-10-02
2024-02-09 2024-02-10 2024-02-11 2024-02-12 2024-05-15 2024-09-16 2024-09-17 2024-09-18
2025-01-28 2025-01-29 2025-01-30 2025-10-05 2025-10-06 2025-10-07 2025-10-08
2026-02-16 2026-02-17 2026-02-18 2026-05-24 2026-06-03 2026-09-24 2026-09-25 2026-09-26 2026-09-27
""".split()

_FIXED_HOLIDAYS = {
    (1, 1),
    (3, 1),
    (5, 5),
    (6, 6),
    (8, 15),
    (10, 3),
    (10, 9),
    (12, 25),
}


def known_holiday_dates(start_year: int = 2017, end_year: int = 2027) -> set[pd.Timestamp]:
    """연도 범위의 고정·이동 공휴일을 정규화된 Timestamp 집합으로 반환한다."""

    dates = {pd.Timestamp(value) for value in _MOVABLE_HOLIDAYS}
    for year in range(start_year, end_year + 1):
        dates.update(pd.Timestamp(year=year, month=month, day=day) for month, day in _FIXED_HOLIDAYS)
    return dates


KNOWN_HOLIDAY_DATES = known_holiday_dates()

EXOGENOUS_COLUMNS = [
    "target_season_code",
    "domestic_travel_index",
    "inbound_travel_index",
    "known_event_flag",
    "event_category",
    "days_to_event",
]


class KnownExogenousCalendar:
    """수요 label을 읽지 않고 예측일에 알려진 외생 변수만 보관·결합한다."""

    def __init__(self, known: pd.DataFrame | None = None) -> None:
        self.known = known if known is not None else pd.DataFrame()

    @classmethod
    def from_files(cls, paths: list[Path]) -> "KnownExogenousCalendar":
        """CSV 달력을 합치며 동일 날짜 값이 충돌하면 ``ValueError``로 거부한다."""

        if not paths:
            return cls()
        columns = ["target_date", *EXOGENOUS_COLUMNS]
        frames = [pd.read_csv(path, usecols=columns) for path in paths]
        combined = pd.concat(frames, ignore_index=True)
        combined["target_date"] = pd.to_datetime(combined["target_date"])
        conflicts = combined.groupby("target_date")[EXOGENOUS_COLUMNS].nunique(
            dropna=False
        )
        if int(conflicts.max().max()) > 1:
            raise ValueError("calendar feature conflict for the same target date")
        known = combined.drop_duplicates("target_date").sort_values("target_date")
        return cls(known[["target_date", *EXOGENOUS_COLUMNS]])

    def enrich(self, frame: pd.DataFrame) -> pd.DataFrame:
        """target_date별 외생 값을 결합하고 누락값은 결정론적 달력값으로 채운다.

        입력에 ``target_date``가 없거나 날짜 변환이 실패하면 pandas 예외를
        그대로 전달하며 원본 DataFrame은 변경하지 않는다.
        """

        result = frame.copy()
        target = pd.to_datetime(result["target_date"])
        day_number = (target - pd.Timestamp("2017-01-01")).dt.days.astype(float)
        trend = (target.dt.year - 2017) / 9.0
        weekend = (target.dt.dayofweek >= 5).astype(float)
        holiday = target.isin(KNOWN_HOLIDAY_DATES).astype(float)
        fallback = pd.DataFrame(index=result.index)
        fallback["target_season_code"] = np.select(
            [
                target.dt.month.isin([12, 1, 2]),
                target.dt.month.isin([3, 4, 5]),
                target.dt.month.isin([6, 7, 8]),
            ],
            ["WINTER", "SPRING", "SUMMER"],
            default="AUTUMN",
        )
        fallback["domestic_travel_index"] = np.clip(
            1.0
            + 0.10 * np.sin(2 * np.pi * day_number / 365.2425)
            + 0.045 * np.sin(4 * np.pi * day_number / 365.2425 + 0.7)
            + 0.055 * trend
            + 0.04 * weekend
            + 0.085 * holiday,
            0.65,
            1.45,
        )
        fallback["inbound_travel_index"] = np.clip(
            0.92
            + 0.07 * np.sin(2 * np.pi * day_number / 365.2425 - 0.8)
            + 0.10 * trend,
            0.60,
            1.35,
        )
        fallback["known_event_flag"] = 0
        fallback["event_category"] = "NONE"
        fallback["days_to_event"] = 999
        if self.known.empty:
            for column in EXOGENOUS_COLUMNS:
                result[column] = fallback[column]
            return result
        lookup = self.known.set_index("target_date")
        for column in EXOGENOUS_COLUMNS:
            mapped = target.map(lookup[column])
            result[column] = mapped.where(mapped.notna(), fallback[column])
        result["known_event_flag"] = result["known_event_flag"].astype(int)
        result["days_to_event"] = result["days_to_event"].astype(int)
        return result
