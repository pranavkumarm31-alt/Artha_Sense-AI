from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX
from xgboost import XGBRegressor


IndicatorCode = Literal[
    "gdp_real_growth",
    "cpi_inflation",
    "wpi_inflation",
    "iip_growth",
]
ModelName = Literal[
    "naive",
    "seasonal_naive",
    "arima",
    "sarima",
    "random_forest",
    "xgboost",
]

MODEL_VERSIONS = {
    "naive": "1.0",
    "seasonal_naive": "1.0",
    "arima": "statsmodels-ARIMA-1.0",
    "sarima": "statsmodels-SARIMA-1.0",
    "random_forest": "sklearn-RF-1.0",
    "xgboost": "xgboost-1.0",
}

INDICATOR_CONFIG = {
    "gdp_real_growth": {"frequency": "quarterly", "seasonal_period": 4, "minimum": 12},
    "cpi_inflation": {"frequency": "monthly", "seasonal_period": 12, "minimum": 24},
    "wpi_inflation": {"frequency": "monthly", "seasonal_period": 12, "minimum": 24},
    "iip_growth": {"frequency": "monthly", "seasonal_period": 12, "minimum": 24},
}


@dataclass(frozen=True)
class ForecastPoint:
    observation_period: str
    observation_start: date
    horizon: int
    value: float
    lower_bound: float | None
    upper_bound: float | None


@dataclass(frozen=True)
class ValidationMetrics:
    mae: float
    rmse: float
    smape: float
    directional_accuracy: float | None
    test_observations: int
    test_period_start: date
    test_period_end: date
    method: str


@dataclass(frozen=True)
class ModelResult:
    model_name: str
    model_version: str
    metrics: ValidationMetrics | None
    forecasts: list[ForecastPoint]
    status: Literal["success", "insufficient_data", "failed"]
    warning: str | None = None


def ensure_finite(values: np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=float)[np.isfinite(np.asarray(values, dtype=float))]


def calculate_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    actual = ensure_finite(actual)
    predicted = ensure_finite(predicted)
    if len(actual) == 0 or len(actual) != len(predicted):
        return {"mae": None, "rmse": None, "smape": None, "directional_accuracy": None}

    errors = predicted - actual
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    denominator = (np.abs(actual) + np.abs(predicted)) / 2.0
    smape = float(
        np.mean(
            np.where(
                denominator > 1e-12,
                np.abs(predicted - actual) / denominator * 100.0,
                0.0,
            )
        )
    )

    directional_accuracy = None
    if len(actual) >= 2:
        actual_direction = np.sign(np.diff(actual))
        predicted_direction = np.sign(np.diff(predicted))
        valid = actual_direction != 0
        if np.any(valid):
            directional_accuracy = float(
                np.mean(actual_direction[valid] == predicted_direction[valid]) * 100.0
            )

    return {
        "mae": mae,
        "rmse": rmse,
        "smape": smape,
        "directional_accuracy": directional_accuracy,
    }


def naive_forecast(history: np.ndarray, horizon: int) -> np.ndarray:
    if len(history) == 0:
        raise ValueError("Naive forecast requires at least one observation.")
    return np.repeat(float(history[-1]), horizon)


def seasonal_naive_forecast(
    history: np.ndarray,
    horizon: int,
    seasonal_period: int,
) -> np.ndarray:
    if len(history) < seasonal_period:
        raise ValueError("Seasonal-naive forecast requires one complete seasonal cycle.")
    season = history[-seasonal_period:]
    return np.array([season[index % seasonal_period] for index in range(horizon)], dtype=float)


def arima_forecast(history: np.ndarray, horizon: int) -> tuple[np.ndarray, np.ndarray | None]:
    if len(history) < 8:
        raise ValueError("ARIMA requires at least eight observations.")
    model = ARIMA(history, order=(1, 1, 0), trend="t")
    fitted = model.fit()
    result = fitted.get_forecast(steps=horizon)
    forecast = np.asarray(result.predicted_mean, dtype=float)
    conf = np.asarray(result.conf_int(alpha=0.20), dtype=float)
    return forecast, conf


def sarima_forecast(
    history: np.ndarray,
    horizon: int,
    seasonal_period: int,
) -> tuple[np.ndarray, np.ndarray | None]:
    minimum = max(12, seasonal_period * 2)
    if len(history) < minimum:
        raise ValueError("SARIMA requires at least two complete seasonal cycles.")
    model = SARIMAX(
        history,
        order=(1, 1, 0),
        seasonal_order=(1, 0, 0, seasonal_period),
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    fitted = model.fit(disp=False, maxiter=100)
    result = fitted.get_forecast(steps=horizon)
    forecast = np.asarray(result.predicted_mean, dtype=float)
    conf = np.asarray(result.conf_int(alpha=0.20), dtype=float)
    return forecast, conf


def lag_features(history: np.ndarray, lag_count: int) -> tuple[np.ndarray, np.ndarray]:
    if len(history) <= lag_count:
        raise ValueError("Lag feature training requires more observations than lag count.")
    x = np.asarray(
        [history[index - lag_count : index] for index in range(lag_count, len(history))],
        dtype=float,
    )
    y = np.asarray(history[lag_count:], dtype=float)
    return x, y


def forest_forecast(history: np.ndarray, horizon: int, lag_count: int) -> np.ndarray:
    x, y = lag_features(history, lag_count)
    model = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(x, y)
    window = history[-lag_count:].copy()
    predictions = []
    for _ in range(horizon):
        prediction = float(model.predict(window.reshape(1, -1))[0])
        predictions.append(prediction)
        window = np.append(window[1:], prediction)
    return np.asarray(predictions, dtype=float)


def xgboost_forecast(history: np.ndarray, horizon: int, lag_count: int) -> np.ndarray:
    x, y = lag_features(history, lag_count)
    model = XGBRegressor(
        n_estimators=150,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(x, y)
    window = history[-lag_count:].copy()
    predictions = []
    for _ in range(horizon):
        prediction = float(model.predict(window.reshape(1, -1))[0])
        predictions.append(prediction)
        window = np.append(window[1:], prediction)
    return np.asarray(predictions, dtype=float)


def empirical_interval(
    residuals: np.ndarray,
    forecasts: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    residuals = ensure_finite(residuals)
    if len(residuals) < 8:
        return None
    lower_offset = float(np.quantile(residuals, 0.10))
    upper_offset = float(np.quantile(residuals, 0.90))
    return forecasts + lower_offset, forecasts + upper_offset


def walk_forward_validation(
    history: np.ndarray,
    dates: pd.DatetimeIndex,
    model_name: ModelName,
    seasonal_period: int,
    horizon: int,
) -> tuple[ValidationMetrics | None, list[float]]:
    lag_count = min(seasonal_period, 12)
    minimum_train = max(seasonal_period * 2, lag_count + 8)
    if len(history) < minimum_train + 3:
        return None, []

    test_start = max(minimum_train, len(history) - min(12, max(3, len(history) // 5)))
    actual: list[float] = []
    predicted: list[float] = []

    for split in range(test_start, len(history)):
        train = history[:split]
        try:
            if model_name == "naive":
                forecast = naive_forecast(train, 1)
            elif model_name == "seasonal_naive":
                forecast = seasonal_naive_forecast(train, 1, seasonal_period)
            elif model_name == "arima":
                forecast, _ = arima_forecast(train, 1)
            elif model_name == "sarima":
                forecast, _ = sarima_forecast(train, 1, seasonal_period)
            elif model_name == "random_forest":
                forecast = forest_forecast(train, 1, lag_count)
            elif model_name == "xgboost":
                forecast = xgboost_forecast(train, 1, lag_count)
            else:
                raise ValueError(f"Unknown model: {model_name}")
        except (ValueError, ArithmeticError, RuntimeError):
            continue

        if np.isfinite(forecast[0]):
            actual.append(float(history[split]))
            predicted.append(float(forecast[0]))

    if len(actual) < 3:
        return None, predicted

    metrics = calculate_metrics(np.asarray(actual), np.asarray(predicted))
    return (
        ValidationMetrics(
            mae=float(metrics["mae"]),
            rmse=float(metrics["rmse"]),
            smape=float(metrics["smape"]),
            directional_accuracy=metrics["directional_accuracy"],
            test_observations=len(actual),
            test_period_start=dates[-len(actual)].date(),
            test_period_end=dates[-1].date(),
            method="rolling-origin walk-forward, one-step retraining",
        ),
        predicted,
    )


def future_period_labels(
    last_date: pd.Timestamp,
    frequency: Literal["monthly", "quarterly"],
    horizon: int,
) -> pd.DatetimeIndex:
    offset = pd.offsets.MonthBegin(1) if frequency == "monthly" else pd.offsets.QuarterBegin(startingMonth=4)
    start = last_date + offset
    return pd.date_range(start=start, periods=horizon, freq=offset)


def generate_model_forecast(
    values: list[tuple[date, str, float]],
    indicator_code: IndicatorCode,
    model_name: ModelName,
    horizon: int,
) -> ModelResult:
    config = INDICATOR_CONFIG[indicator_code]
    frequency = config["frequency"]
    seasonal_period = int(config["seasonal_period"])
    minimum = int(config["minimum"])

    if len(values) < minimum:
        return ModelResult(
            model_name=model_name,
            model_version=MODEL_VERSIONS[model_name],
            metrics=None,
            forecasts=[],
            status="insufficient_data",
            warning=(
                f"{indicator_code} has {len(values)} observations; "
                f"at least {minimum} are required for this frequency."
            ),
        )

    ordered = sorted(values, key=lambda item: item[0])
    dates = pd.DatetimeIndex([pd.Timestamp(item[0]) for item in ordered])
    history = np.asarray([item[2] for item in ordered], dtype=float)
    history = ensure_finite(history)
    if len(history) != len(ordered):
        return ModelResult(
            model_name=model_name,
            model_version=MODEL_VERSIONS[model_name],
            metrics=None,
            forecasts=[],
            status="insufficient_data",
            warning="The series contains missing or non-finite values; no forecast was generated.",
        )

    metrics, walk_predictions = walk_forward_validation(
        history,
        dates,
        model_name,
        seasonal_period,
        horizon,
    )

    try:
        intervals = None
        if model_name == "naive":
            forecast = naive_forecast(history, horizon)
        elif model_name == "seasonal_naive":
            forecast = seasonal_naive_forecast(history, horizon, seasonal_period)
        elif model_name == "arima":
            forecast, intervals = arima_forecast(history, horizon)
        elif model_name == "sarima":
            forecast, intervals = sarima_forecast(history, horizon, seasonal_period)
        elif model_name == "random_forest":
            lag_count = min(seasonal_period, 12)
            forecast = forest_forecast(history, horizon, lag_count)
        elif model_name == "xgboost":
            lag_count = min(seasonal_period, 12)
            forecast = xgboost_forecast(history, horizon, lag_count)
        else:
            raise ValueError(f"Unknown model: {model_name}")
    except (ValueError, ArithmeticError, RuntimeError) as error:
        return ModelResult(
            model_name=model_name,
            model_version=MODEL_VERSIONS[model_name],
            metrics=metrics,
            forecasts=[],
            status="failed",
            warning=str(error),
        )

    if intervals is None:
        residual_predictions = np.asarray(walk_predictions, dtype=float)
        if len(residual_predictions) >= 8:
            residual_start = max(1, len(history) - len(residual_predictions))
            residual_actual = history[residual_start:]
            residuals = residual_actual[: len(residual_predictions)] - residual_predictions
            empirical = empirical_interval(residuals, forecast)
            if empirical is not None:
                intervals = np.column_stack(empirical)

    future_dates = future_period_labels(
        pd.Timestamp(ordered[-1][0]),
        frequency,
        horizon,
    )
    points: list[ForecastPoint] = []
    for index, future_date in enumerate(future_dates):
        if frequency == "monthly":
            observation_period = future_date.strftime("%b %Y")
        else:
            quarter = ((future_date.month - 4) % 12) // 3 + 1
            fiscal_start = future_date.year if future_date.month >= 4 else future_date.year - 1
            observation_period = f"Q{quarter} FY {fiscal_start}-{str(fiscal_start + 1)[-2:]}"

        lower = upper = None
        if intervals is not None:
            lower = float(intervals[index][0])
            upper = float(intervals[index][1])
        points.append(
            ForecastPoint(
                observation_period=observation_period,
                observation_start=future_date.date().replace(day=1),
                horizon=index + 1,
                value=float(forecast[index]),
                lower_bound=lower,
                upper_bound=upper,
            )
        )

    return ModelResult(
        model_name=model_name,
        model_version=MODEL_VERSIONS[model_name],
        metrics=metrics,
        forecasts=points,
        status="success",
        warning=None,
    )
