from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from statsmodels.tsa.seasonal import seasonal_decompose


DetectionMethod = Literal["zscore", "rolling", "isolation_forest", "seasonal_residual"]
Severity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class AnomalyPoint:
    observation_start: date
    observation_period: str
    actual_value: float
    expected_value: float
    absolute_deviation: float
    percentage_deviation: float | None
    anomaly_score: float
    severity: Severity
    detection_method: DetectionMethod
    model_version: str
    explanation: str
    source_key: str
    source_name: str
    source_url: str
    detected_at: datetime


def classify_severity(score: float, threshold: float, method: DetectionMethod) -> Severity:
    magnitude = abs(float(score))
    if method == "isolation_forest":
        if magnitude >= 0.15:
            return "high"
        if magnitude >= 0.10:
            return "medium"
        if magnitude >= 0.05:
            return "low"
        return "low"
    if magnitude >= threshold * 1.5:
        return "high"
    if magnitude >= threshold * 1.25:
        return "medium"
    return "low"


def zscore_detection(
    observations: list[dict[str, object]],
    threshold: float = 2.5,
    rolling_window: int | None = None,
) -> list[AnomalyPoint]:
    values = np.asarray([float(row["value"]) for row in observations], dtype=float)
    if len(values) < 3:
        return []

    method: DetectionMethod = "rolling" if rolling_window else "zscore"
    detected: list[AnomalyPoint] = []
    for index, row in enumerate(observations):
        if rolling_window:
            start = max(0, index - rolling_window)
            baseline = values[start:index]
            if len(baseline) < max(3, rolling_window // 2):
                continue
        else:
            baseline = values

        expected = float(np.mean(baseline))
        std = float(np.std(baseline, ddof=1)) if len(baseline) >= 2 else 0.0
        actual = float(row["value"])
        if std <= 1e-12:
            continue
        score = (actual - expected) / std
        if abs(score) < threshold:
            continue
        deviation = actual - expected
        percentage = deviation / abs(expected) * 100.0 if expected != 0 else None
        detected.append(
            make_anomaly(
                row=row,
                expected=expected,
                deviation=deviation,
                percentage=percentage,
                score=score,
                method=method,
                severity=classify_severity(score, threshold, method),
                model_version="zscore-rolling-1.0" if rolling_window else "zscore-historical-1.0",
                explanation=(
                    f"Observed value differs from the "
                    f"{'rolling ' if rolling_window else 'historical '}baseline by "
                    f"{abs(score):.2f} standard deviations."
                ),
            )
        )
    return detected


def isolation_forest_detection(
    observations: list[dict[str, object]],
    contamination: float = 0.05,
) -> list[AnomalyPoint]:
    values = np.asarray([float(row["value"]) for row in observations], dtype=float)
    minimum_train = 12
    if len(values) < minimum_train + 3:
        return []

    features = []
    for index in range(len(values)):
        lag1 = values[index - 1] if index >= 1 else values[index]
        lag2 = values[index - 2] if index >= 2 else lag1
        prior = values[max(0, index - 6):index]
        rolling_mean = float(np.mean(prior)) if len(prior) else float(values[index])
        rolling_std = float(np.std(prior, ddof=1)) if len(prior) >= 2 else 0.0
        features.append([values[index], lag1, lag2, rolling_mean, rolling_std])
    features_array = np.asarray(features, dtype=float)

    detected: list[AnomalyPoint] = []
    for index in range(minimum_train, len(observations)):
        training_features = features_array[max(0, index - minimum_train):index]
        model = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            random_state=42,
        )
        model.fit(training_features)
        score = float(-model.score_samples(features_array[index:index + 1])[0])
        prediction = int(model.predict(features_array[index:index + 1])[0])
        if prediction == 1:
            continue
        expected = float(np.mean(values[max(0, index - 12):index]))
        deviation = float(values[index] - expected)
        percentage = deviation / abs(expected) * 100.0 if expected != 0 else None
        detected.append(
            make_anomaly(
                row=observations[index],
                expected=expected,
                deviation=deviation,
                percentage=percentage,
                score=score,
                method="isolation_forest",
                severity=classify_severity(score, 0.10, "isolation_forest"),
                model_version="scikit-learn-isolation-forest-1.0",
                explanation=(
                    "Isolation Forest identified this observation outside the prior "
                    "lag, rolling mean and rolling volatility feature distribution."
                ),
            )
        )
    return detected


def seasonal_residual_detection(
    observations: list[dict[str, object]],
    frequency: Literal["monthly", "quarterly"],
    threshold: float = 2.5,
) -> list[AnomalyPoint]:
    period = 12 if frequency == "monthly" else 4
    if len(observations) < period * 3:
        return []

    dates = pd.DatetimeIndex([pd.Timestamp(row["observation_start"]) for row in observations])
    values = pd.Series(
        [float(row["value"]) for row in observations],
        index=dates,
        dtype=float,
    ).sort_index()
    try:
        decomposition = seasonal_decompose(
            values,
            model="additive",
            period=period,
            extrapolate_trend="period",
        )
    except (ValueError, FloatingPointError):
        return []

    residual = decomposition.resid.dropna()
    if len(residual) < 3:
        return []
    residual_std = float(residual.std(ddof=1))
    if residual_std <= 1e-12:
        return []
    residual_mean = float(residual.mean())

    detected: list[AnomalyPoint] = []
    by_date = {pd.Timestamp(row["observation_start"]): row for row in observations}
    for timestamp, residual_value in residual.items():
        score = (float(residual_value) - residual_mean) / residual_std
        if abs(score) < threshold:
            continue
        row = by_date.get(pd.Timestamp(timestamp))
        if row is None:
            continue
        baseline = float(decomposition.trend.loc[timestamp] + decomposition.seasonal.loc[timestamp])
        actual = float(row["value"])
        deviation = actual - baseline
        percentage = deviation / abs(baseline) * 100.0 if baseline != 0 else None
        detected.append(
            make_anomaly(
                row=row,
                expected=baseline,
                deviation=deviation,
                percentage=percentage,
                score=score,
                method="seasonal_residual",
                severity=classify_severity(score, threshold, "seasonal_residual"),
                model_version=f"statsmodels-seasonal-residual-{period}-period-1.0",
                explanation=(
                    f"Seasonal residual exceeds {threshold:.2f} standard deviations "
                    f"after additive trend and seasonal component removal."
                ),
            )
        )
    return detected


def make_anomaly(
    *,
    row: dict[str, object],
    expected: float,
    deviation: float,
    percentage: float | None,
    score: float,
    method: DetectionMethod,
    severity: Severity,
    model_version: str,
    explanation: str,
) -> AnomalyPoint:
    return AnomalyPoint(
        observation_start=date.fromisoformat(str(row["observation_start"])) if isinstance(row["observation_start"], date) else pd.Timestamp(row["observation_start"]).date(),
        observation_period=str(row["observation_period"]),
        actual_value=float(row["value"]),
        expected_value=expected,
        absolute_deviation=deviation,
        percentage_deviation=percentage,
        anomaly_score=score,
        severity=severity,
        detection_method=method,
        model_version=model_version,
        explanation=explanation,
        source_key=str(row["source_key"]),
        source_name=str(row["source_name"]),
        source_url=str(row["source_url"]),
        detected_at=datetime.now(timezone.utc),
    )
