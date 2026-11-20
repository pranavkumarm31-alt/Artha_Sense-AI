from __future__ import annotations

from datetime import date
from typing import Literal

from .trend_analysis import classify_trend, percentage_change, point_change


Classification = Literal["positive", "negative", "neutral"]


def generate_insights(
    indicator_code: str,
    observations: list[dict[str, object]],
) -> list[dict[str, object]]:
    ordered = sorted(observations, key=lambda row: str(row["observation_start"]))
    if len(ordered) < 2:
        return []

    latest = ordered[-1]
    previous = ordered[-2]
    lag = 4 if indicator_code == "gdp_real_growth" else 12
    prior_year = ordered[-lag - 1] if len(ordered) > lag else None

    latest_value = float(latest["value"])
    previous_value = float(previous["value"])
    period_change = latest_value - previous_value
    yoy_change = (
        latest_value - float(prior_year["value"])
        if prior_year is not None
        else None
    )

    if "inflation" in indicator_code:
        indicator_label = "CPI inflation" if indicator_code == "cpi_inflation" else "WPI inflation"
        classification: Classification
        if period_change > 0.15:
            classification = "negative"
            direction = "risen"
        elif period_change < -0.15:
            classification = "positive"
            direction = "fallen"
        else:
            classification = "neutral"
            direction = "been broadly stable"
        change_text = f"{abs(period_change):.2f} percentage points"
    elif indicator_code == "gdp_real_growth":
        indicator_label = "GDP growth"
        if period_change < -0.15:
            classification = "negative"
            direction = "slowed"
        elif period_change > 0.15:
            classification = "positive"
            direction = "accelerated"
        else:
            classification = "neutral"
            direction = "been broadly stable"
        change_text = f"{abs(period_change):.2f} percentage points"
    elif indicator_code == "iip_growth":
        indicator_label = "IIP growth"
        if period_change > 0.15:
            classification = "positive"
            direction = "accelerated"
        elif period_change < -0.15:
            classification = "negative"
            direction = "contracted"
        else:
            classification = "neutral"
            direction = "been broadly stable"
        change_text = f"{abs(period_change):.2f} percentage points"
    else:
        indicator_label = indicator_code
        classification = "neutral"
        direction = "changed"
        change_text = f"{abs(period_change):.2f} percentage points"

    trend_values = [float(row["value"]) for row in ordered[-6:] if row["value"] is not None]
    trend = classify_trend(trend_values)
    insight = (
        f"{indicator_label} has {direction} from {previous_value:.2f}% "
        f"to {latest_value:.2f}% in {latest['observation_period']}, "
        f"a change of {change_text}."
    )
    return [
        {
            "indicator_code": indicator_code,
            "indicator": indicator_label,
            "observation_period": latest["observation_period"],
            "observation_start": latest["observation_start"],
            "actual_value": latest_value,
            "comparison_period": previous["observation_period"],
            "comparison_value": previous_value,
            "magnitude": period_change,
            "magnitude_unit": "percentage_points",
            "year_on_year_change": yoy_change,
            "classification": classification,
            "evidence_strength": "high" if len(ordered) >= lag else "limited",
            "trend": trend,
            "calculation": "latest value minus immediately preceding valid observation",
            "insight": insight,
            "source": latest["source_name"],
            "source_url": latest["source_url"],
            "interpretation": "Statistical observation; no causal claim.",
        }
    ]
