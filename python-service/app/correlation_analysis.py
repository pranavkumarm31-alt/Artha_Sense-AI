from __future__ import annotations

from datetime import date
from typing import TypedDict

import numpy as np
import pandas as pd


class AlignedPeriods(TypedDict):
    left: str | list[str]
    right: str | list[str]


class CorrelationResult(TypedDict):
    correlation: float | None
    sample_size: int
    method: str
    caveat: str
    input_periods: list[AlignedPeriods]


def pearson_correlation(
    left: list[tuple[date, str, float]],
    right: list[tuple[date, str, float]],
    *,
    aggregate_right_quarterly: bool = False,
) -> CorrelationResult:
    frequency = "Q-APR" if aggregate_right_quarterly else "M"
    left_periods_by_key: dict[str, list[str]] = {}
    right_periods_by_key: dict[str, list[str]] = {}
    for observations, period_map in (
        (left, left_periods_by_key),
        (right, right_periods_by_key),
    ):
        for observation_date, observation_period, value in observations:
            if np.isfinite(value):
                key = str(pd.Timestamp(observation_date).to_period(frequency))
                period_map.setdefault(key, []).append(observation_period)

    left_frame = pd.DataFrame(
        [{"date": pd.Timestamp(start), "period": period, "value": value}
         for start, period, value in left],
    )
    right_frame = pd.DataFrame(
        [{"date": pd.Timestamp(start), "period": period, "value": value}
         for start, period, value in right],
    )
    if left_frame.empty or right_frame.empty:
        return {
            "correlation": None,
            "sample_size": 0,
            "method": "Pearson",
            "caveat": "Insufficient aligned observations.",
            "input_periods": [],
        }

    if aggregate_right_quarterly:
        left_frame["quarter"] = left_frame["date"].dt.to_period("Q-APR")
        left_frame = left_frame.groupby("quarter", as_index=False)["value"].mean()
        right_frame["quarter"] = right_frame["date"].dt.to_period("Q-APR")
        right_frame = right_frame.groupby("quarter", as_index=False)["value"].mean()
        aligned = left_frame.merge(right_frame, on="quarter", suffixes=("_left", "_right"))
    else:
        left_frame["month"] = left_frame["date"].dt.to_period("M")
        right_frame["month"] = right_frame["date"].dt.to_period("M")
        aligned = left_frame.merge(
            right_frame,
            on="month",
            suffixes=("_left", "_right"),
        )
    aligned["value_left"] = aligned["value_left"].replace([np.inf, -np.inf], np.nan)
    aligned["value_right"] = aligned["value_right"].replace([np.inf, -np.inf], np.nan)
    aligned = aligned.dropna(subset=["value_left", "value_right"])
    common_keys = sorted(left_periods_by_key.keys() & right_periods_by_key.keys())
    input_periods: list[AlignedPeriods] = [
        {
            "left": left_periods_by_key[key],
            "right": right_periods_by_key[key],
        }
        for key in common_keys
    ]

    if len(aligned) < 3:
        return {
            "correlation": None,
            "sample_size": int(len(aligned)),
            "method": "Pearson",
            "caveat": "At least three aligned observations are required.",
            "input_periods": input_periods,
        }

    correlation = float(aligned[["value_left", "value_right"]].corr(method="pearson").iloc[0, 1])
    if not np.isfinite(correlation):
        correlation = None
    return {
        "correlation": round(correlation, 6) if correlation is not None else None,
        "sample_size": int(len(aligned)),
        "method": "Pearson",
        "caveat": "Correlation does not imply causation.",
        "input_periods": input_periods,
    }
