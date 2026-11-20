from datetime import date

import numpy as np
import pytest

from app.correlation_analysis import pearson_correlation
from app.economic_insights import generate_insights
from app.trend_analysis import (
    moving_average,
    percentage_change,
    percentage_deviation,
    point_change,
    rolling_volatility,
)


def test_percentage_change_handles_zero_and_missing() -> None:
    assert percentage_change(110.0, 100.0) == pytest.approx(10.0)
    assert percentage_change(10.0, 0.0) is None
    assert percentage_change(None, 100.0) is None


def test_point_change_is_percentage_point_difference() -> None:
    assert point_change(7.8, 7.2) == pytest.approx(0.6)


def test_moving_average_requires_available_observations() -> None:
    assert moving_average([1.0, 3.0, 5.0], 3) == [None, None, 3.0]
    assert moving_average([1.0, None, 5.0, 7.0], 3) == [None, None, None, None]


def test_rolling_volatility_is_missing_until_window_is_full() -> None:
    assert rolling_volatility([1.0, 2.0, 3.0, 4.0], 3) == [None, None, pytest.approx(1.0), pytest.approx(1.0)]


def test_percentage_deviation_handles_zero_average() -> None:
    assert percentage_deviation(110.0, 100.0) == pytest.approx(10.0)
    assert percentage_deviation(10.0, 0.0) is None


def test_correlation_aligns_exact_months_and_reports_sample_size() -> None:
    left = [
        (date(2026, 1, 1), "Jan 2026", 2.0),
        (date(2026, 2, 1), "Feb 2026", 3.0),
        (date(2026, 3, 1), "Mar 2026", 4.0),
    ]
    right = [
        (date(2026, 1, 1), "Jan 2026", 20.0),
        (date(2026, 2, 1), "Feb 2026", 30.0),
        (date(2026, 3, 1), "Mar 2026", 40.0),
    ]
    result = pearson_correlation(left, right)
    assert result["sample_size"] == 3
    assert result["correlation"] == pytest.approx(1.0)
    assert result["input_periods"][0] == {
        "left": ["Jan 2026"],
        "right": ["Jan 2026"],
    }


def test_correlation_requires_three_pairs() -> None:
    left = [(date(2026, 1, 1), "Jan 2026", 2.0)]
    right = [(date(2026, 1, 1), "Jan 2026", 20.0)]
    result = pearson_correlation(left, right)
    assert result["correlation"] is None
    assert result["sample_size"] == 1


def test_insights_are_derived_without_fabrication() -> None:
    observations = [
        {
            "observation_start": date(2025, 1, 1),
            "observation_period": "Jan 2025",
            "value": 4.0,
            "source_name": "MoSPI",
            "source_url": "https://mcp.mospi.gov.in/",
        },
        {
            "observation_start": date(2025, 2, 1),
            "observation_period": "Feb 2025",
            "value": 5.0,
            "source_name": "MoSPI",
            "source_url": "https://mcp.mospi.gov.in/",
        },
    ]
    result = generate_insights("cpi_inflation", observations)
    assert len(result) == 1
    assert result[0]["actual_value"] == 5.0
    assert result[0]["comparison_value"] == 4.0
    assert result[0]["magnitude"] == pytest.approx(1.0)
    assert result[0]["magnitude_unit"] == "percentage_points"
