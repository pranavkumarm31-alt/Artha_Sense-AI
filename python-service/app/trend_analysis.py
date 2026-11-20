from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal, TypedDict

import numpy as np
import pandas as pd


Frequency = Literal["monthly", "quarterly"]


@dataclass(frozen=True)
class TrendPoint:
    observation_start: date
    observation_period: str
    value: float
    change: float | None
    yoy_change: float | None
    moving_average_3: float | None
    moving_average_6: float | None
    moving_average_12: float | None
    rolling_volatility_3: float | None
    deviation_from_ma: float | None


class AnalysisPoint(TypedDict):
    observation_start: date
    observation_period: str
    value: float | None
    period_change: float | None
    year_on_year_change: float | None
    year_on_year_percent_change: float | None
    moving_average_3: float | None
    moving_average_6: float | None
    moving_average_12: float | None
    rolling_volatility_3: float | None
    deviation_from_ma: float | None


def percentage_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or not math.isfinite(current) or not math.isfinite(previous):
        return None
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def point_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or not math.isfinite(current) or not math.isfinite(previous):
        return None
    return current - previous


def quarter_on_quarter_annualized(current: float, previous: float) -> float | None:
    if previous <= -100:
        return None
    qoq_fraction = current / 100.0 - previous / 100.0
    growth_factor = 1.0 + qoq_fraction
    if growth_factor <= 0:
        return None
    return (growth_factor**4 - 1.0) * 100.0


def moving_average(values: list[float | None], window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("Moving-average window must be positive.")
    result: list[float | None] = []
    for index in range(len(values)):
        sample = values[max(0, index - window + 1): index + 1]
        finite = [value for value in sample if value is not None and math.isfinite(value)]
        result.append(sum(finite) / len(finite) if len(finite) == window else None)
    return result


def rolling_volatility(values: list[float | None], window: int) -> list[float | None]:
    if window < 2:
        raise ValueError("Rolling volatility window must be at least two.")
    result: list[float | None] = []
    for index in range(len(values)):
        sample = values[max(0, index - window + 1): index + 1]
        finite = [value for value in sample if value is not None and math.isfinite(value)]
        if len(finite) < window:
            result.append(None)
        else:
            result.append(float(np.std(np.asarray(finite), ddof=1)))
    return result


def percentage_deviation(value: float | None, average: float | None) -> float | None:
    if value is None or average is None or not math.isfinite(value) or not math.isfinite(average):
        return None
    if average == 0:
        return None
    return (value - average) / abs(average) * 100.0


def classify_trend(values: list[float | None]) -> str:
    finite = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(finite) < 3:
        return "insufficient_data"
    recent = finite[-6:]
    x = np.asarray([index for index, _ in recent], dtype=float)
    y = np.asarray([value for _, value in recent], dtype=float)
    slope = float(np.polyfit(x, y, 1)[0]) if len(recent) >= 2 else 0.0
    if slope > 0.15:
        return "upward"
    if slope < -0.15:
        return "downward"
    return "stable"


def classify_change_direction(values: list[float | None]) -> str:
    finite = [value for value in values if value is not None]
    if len(finite) < 3:
        return "insufficient_data"
    latest_change = finite[-1] - finite[-2]
    previous_change = finite[-2] - finite[-3]
    acceleration = latest_change - previous_change
    if acceleration > 0.15:
        return "accelerating"
    if acceleration < -0.15:
        return "decelerating"
    return "stable"


def build_growth_series(
    observations: list[dict[str, object]],
    frequency: Frequency,
) -> list[AnalysisPoint]:
    ordered = sorted(observations, key=lambda row: pd.Timestamp(str(row["observation_start"])))
    values: list[float | None] = [
        float(row["value"]) if row["value"] is not None else None
        for row in ordered
    ]
    lag = 4 if frequency == "quarterly" else 12
    previous = [
        values[index - 1] if index > 0 else None
        for index in range(len(values))
    ]
    yoy = [
        values[index - lag] if index >= lag else None
        for index in range(len(values))
    ]
    point_changes = [
        point_change(current, previous[index])
        for index, current in enumerate(values)
    ]
    yoy_changes = [
        point_change(current, yoy[index])
        for index, current in enumerate(values)
    ]
    ma3 = moving_average(values, 3)
    ma6 = moving_average(values, 6)
    ma12 = moving_average(values, 12 if frequency == "monthly" else 4)
    vol3 = rolling_volatility(values, 3)

    result = []
    for index, row in enumerate(ordered):
        ma = ma3[index]
        result.append(
            {
                "observation_start": pd.Timestamp(str(row["observation_start"])).date(),
                "observation_period": str(row["observation_period"]),
                "value": values[index],
                "period_change": point_changes[index],
                "year_on_year_change": yoy_changes[index],
                "year_on_year_percent_change": percentage_change(values[index], yoy[index]),
                "moving_average_3": ma,
                "moving_average_6": ma6[index],
                "moving_average_12": ma12[index],
                "rolling_volatility_3": vol3[index],
                "deviation_from_ma": percentage_deviation(values[index], ma),
            }
        )
    return result


def trend_summary(
    growth_series: list[dict[str, object]],
) -> dict[str, object]:
    values = [row["value"] for row in growth_series]
    changes = [row["period_change"] for row in growth_series]
    yoy = [row["year_on_year_change"] for row in growth_series]
    latest = growth_series[-1] if growth_series else None
    return {
        "trend": classify_trend([value for value in values if isinstance(value, (int, float))]),
        "change_direction": classify_change_direction(
            [change for change in changes if isinstance(change, (int, float))]
        ),
        "latest": latest,
        "observation_count": len(growth_series),
    }
