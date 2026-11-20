from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.forecasting import (
    arima_forecast,
    calculate_metrics,
    forest_forecast,
    generate_model_forecast,
    naive_forecast,
    sarima_forecast,
    seasonal_naive_forecast,
    walk_forward_validation,
)


def test_naive_and_seasonal_naive_forecasts_are_deterministic() -> None:
    history = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=float)
    np.testing.assert_array_equal(naive_forecast(history, 3), [4.0, 4.0, 4.0])
    np.testing.assert_array_equal(
        seasonal_naive_forecast(history, 6, 2),
        [3.0, 4.0, 3.0, 4.0, 3.0, 4.0],
    )


def test_metrics_are_calculated_without_fabricating_values() -> None:
    metrics = calculate_metrics(
        np.asarray([10.0, 12.0, 14.0]),
        np.asarray([9.0, 13.0, 13.0]),
    )
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(1.0)
    assert metrics["directional_accuracy"] == pytest.approx(50.0)


def test_insufficient_observations_return_honest_status() -> None:
    values = [(date(2025, index + 1, 1), f"{index}", 2.0 + index) for index in range(10)]
    result = generate_model_forecast(values, "iip_growth", "naive", 3)
    assert result.status == "insufficient_data"
    assert result.forecasts == []
    assert "at least 24" in (result.warning or "")


def test_walk_forward_validation_uses_only_prior_observations() -> None:
    history = np.asarray([float(i % 12) for i in range(36)], dtype=float)
    dates = pd.date_range("2023-01-01", periods=36, freq="MS")
    metrics, predictions = walk_forward_validation(
        history,
        pd.DatetimeIndex(dates),
        "naive",
        12,
        1,
    )
    assert metrics is not None
    assert len(predictions) >= 3
    assert metrics.test_observations == len(predictions)


def test_random_forest_produces_finite_forecast_from_lags() -> None:
    history = np.asarray([float(index + (index % 3)) for index in range(30)], dtype=float)
    forecast = forest_forecast(history, 3, 12)
    assert len(forecast) == 3
    assert np.isfinite(forecast).all()


def test_gdp_horizon_validation() -> None:
    values = [(date(2020 + index // 4, 1 + (index % 4) * 3, 1), str(index), 6.0 + index * 0.1)
              for index in range(16)]
    result = generate_model_forecast(values, "gdp_real_growth", "naive", 2)
    assert result.status == "success"
    assert len(result.forecasts) == 2


def test_arima_and_sarima_return_finite_forecasts() -> None:
    history = np.asarray(
        [10.0 + (index % 12) * 0.25 + index * 0.01 for index in range(36)],
        dtype=float,
    )
    arima_forecast_values, arima_interval = arima_forecast(history, 3)
    sarima_forecast_values, sarima_interval = sarima_forecast(history, 3, 12)

    assert len(arima_forecast_values) == 3
    assert np.isfinite(arima_forecast_values).all()
    assert arima_interval is None or arima_interval.shape == (3, 2)
    assert len(sarima_forecast_values) == 3
    assert np.isfinite(sarima_forecast_values).all()
    assert sarima_interval is None or sarima_interval.shape == (3, 2)
