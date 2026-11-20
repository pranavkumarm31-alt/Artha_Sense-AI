from __future__ import annotations

from datetime import date
from typing import TypedDict

import numpy as np
import pandas as pd


class AlignedPeriods(TypedDict):
    left: list[str]
    right: list[str]


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
    """
    Calculate Pearson correlation between two economic indicators.

    Monthly observations are aligned by month.
    When aggregate_right_quarterly is True, both datasets are
    aggregated by quarter before calculating correlation.
    """

    frequency = "Q-APR" if aggregate_right_quarterly else "M"

    left_values: dict[str, list[float]] = {}
    right_values: dict[str, list[float]] = {}

    left_periods: dict[str, list[str]] = {}
    right_periods: dict[str, list[str]] = {}

    def collect_observations(
        observations: list[tuple[date, str, float]],
        values_by_period: dict[str, list[float]],
        labels_by_period: dict[str, list[str]],
    ) -> None:
        for observation_date, observation_period, value in observations:
            numeric_value = float(value)

            if not np.isfinite(numeric_value):
                continue

            key = str(
                pd.Timestamp(observation_date).to_period(frequency)
            )

            values_by_period.setdefault(key, []).append(numeric_value)
            labels_by_period.setdefault(key, []).append(observation_period)

    collect_observations(left, left_values, left_periods)
    collect_observations(right, right_values, right_periods)

    common_keys = sorted(
        left_values.keys() & right_values.keys()
    )

    if not common_keys:
        return {
            "correlation": None,
            "sample_size": 0,
            "method": "Pearson",
            "caveat": "Insufficient aligned observations.",
            "input_periods": [],
        }

    aligned_left: list[float] = []
    aligned_right: list[float] = []

    input_periods: list[AlignedPeriods] = []

    for key in common_keys:
        left_period_values = left_values[key]
        right_period_values = right_values[key]

        # Average observations within each aligned period.
        left_average = float(np.mean(left_period_values))
        right_average = float(np.mean(right_period_values))

        aligned_left.append(left_average)
        aligned_right.append(right_average)

        input_periods.append(
            {
                "left": left_periods[key],
                "right": right_periods[key],
            }
        )

    sample_size = len(aligned_left)

    if sample_size < 3:
        return {
            "correlation": None,
            "sample_size": sample_size,
            "method": "Pearson",
            "caveat": "At least three aligned observations are required.",
            "input_periods": input_periods,
        }

    left_array = np.asarray(aligned_left, dtype=np.float64)
    right_array = np.asarray(aligned_right, dtype=np.float64)

    # Pearson correlation is undefined for constant-valued data.
    if np.std(left_array) == 0 or np.std(right_array) == 0:
        return {
            "correlation": None,
            "sample_size": sample_size,
            "method": "Pearson",
            "caveat": "Correlation is undefined when either series has zero variance.",
            "input_periods": input_periods,
        }

    correlation_value = float(
        np.corrcoef(left_array, right_array)[0, 1]
    )

    if not np.isfinite(correlation_value):
        correlation: float | None = None
    else:
        correlation = round(correlation_value, 6)

    return {
        "correlation": correlation,
        "sample_size": sample_size,
        "method": "Pearson",
        "caveat": "Correlation does not imply causation.",
        "input_periods": input_periods,
    }