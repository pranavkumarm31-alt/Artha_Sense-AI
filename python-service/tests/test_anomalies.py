from datetime import date

import pytest

from app.anomaly_detection import (
    classify_severity,
    isolation_forest_detection,
    seasonal_residual_detection,
    zscore_detection,
)


def observations(values: list[float], start_year: int = 2024) -> list[dict[str, object]]:
    return [
        {
            "observation_start": date(
                start_year + index // 12,
                index % 12 + 1,
                1,
            ),
            "observation_period": f"{index % 12 + 1}/{start_year + index // 12}",
            "value": value,
            "source_key": "wpi",
            "source_name": "Ministry of Statistics and Programme Implementation (MoSPI)",
            "source_url": "https://mcp.mospi.gov.in/",
        }
        for index, value in enumerate(values)
    ]


def test_zscore_detects_large_historical_deviation() -> None:
    rows = observations([100.0, 101.0, 99.0, 100.5, 100.0, 150.0])
    detected = zscore_detection(rows, threshold=2.0)
    assert any(item.observation_period == "6/2024" for item in detected)


def test_zero_standard_deviation_is_ignored() -> None:
    assert zscore_detection(observations([5.0] * 6), threshold=2.0) == []


def test_rolling_zscore_requires_prior_window() -> None:
    rows = observations([90.0, 100.0, 110.0, 95.0, 105.0, 150.0])
    detected = zscore_detection(rows, threshold=2.0, rolling_window=3)
    assert len(detected) >= 1


def test_isolation_forest_requires_sufficient_history() -> None:
    assert isolation_forest_detection(observations([100.0] * 10), contamination=0.05) == []
    detected = isolation_forest_detection(
        observations([100.0 + (index % 5) for index in range(40)] + [180.0]),
        contamination=0.05,
    )
    assert isinstance(detected, list)


def test_seasonal_residual_requires_three_cycles() -> None:
    short = observations([100.0 + (index % 12) for index in range(24)])
    assert seasonal_residual_detection(short, "monthly", threshold=2.5) == []

    long = observations(
        [100.0 + (index % 12) * 2 + (180.0 if index == 35 else 0.0) for index in range(36)]
    )
    detected = seasonal_residual_detection(long, "monthly", threshold=2.0)
    assert isinstance(detected, list)


@pytest.mark.parametrize(
    ("score", "severity"),
    [
        (2.6, "low"),
        (3.2, "medium"),
        (4.0, "high"),
    ],
)
def test_severity_thresholds(score: float, severity: str) -> None:
    assert classify_severity(score, 2.5, "zscore") == severity
