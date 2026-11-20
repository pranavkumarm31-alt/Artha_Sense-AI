import math
import re
from datetime import date
from typing import Any, cast

from . import database
from .correlation_analysis import pearson_correlation
from .economic_insights import generate_insights
from .embedding_service import embed_texts
from .trend_analysis import build_growth_series, classify_change_direction, classify_trend


_INDICATOR_TERMS: dict[str, tuple[str, ...]] = {
    "gdp_real_growth": ("gdp", "gross domestic product"),
    "gva_agriculture": ("gva agriculture", "agriculture gva"),
    "gva_industry": ("gva industry", "industry gva"),
    "gva_services": ("gva services", "services gva"),
    "cpi_inflation": ("cpi", "consumer price", "retail inflation"),
    "wpi_inflation": ("wpi", "wholesale price"),
    "iip_growth": ("iip", "industrial production"),
}
_STOP_WORDS = {
    "what", "when", "where", "which", "who", "how", "the", "and", "for", "from",
    "with", "about", "latest", "india", "indias", "is", "are", "was", "were", "of",
    "to", "in", "on", "a", "an", "it", "its", "compare", "explain", "show",
}


def infer_indicator(query: str) -> str | None:
    lowered = query.lower()
    for code, terms in _INDICATOR_TERMS.items():
        if any(term in lowered for term in terms):
            return code
    return None


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in _STOP_WORDS
    }


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    vector: list[float] = []
    for item in cast(list[object], value):
        if not isinstance(item, (int, float)) or not math.isfinite(item):
            return []
        vector.append(float(item))
    return vector


def _json_object(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


async def retrieve_evidence(
    query: str,
    *,
    indicator_code: str | None = None,
    source: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    selected_indicator = indicator_code or infer_indicator(query)
    structured = database.get_structured_research_evidence(
        indicator_code=selected_indicator,
        start=start,
        end=end,
    )
    lowered_query = query.lower()
    if any(term in lowered_query for term in ("correlation", "correlate", "relationship", "related")):
        pairs = [
            ("gdp_real_growth", "iip_growth", True),
            ("cpi_inflation", "wpi_inflation", False),
            ("gdp_real_growth", "cpi_inflation", True),
            ("iip_growth", "wpi_inflation", False),
        ]
        explicit_pairs = [
            pair for pair in pairs
            if any(term in lowered_query for term in _INDICATOR_TERMS[pair[0]])
            and any(term in lowered_query for term in _INDICATOR_TERMS[pair[1]])
        ]
        for left_code, right_code, aggregate_quarterly in explicit_pairs or pairs:
            left_history = database.get_history_range(left_code, start, end, limit=10000)
            right_history = database.get_history_range(right_code, start, end, limit=10000)
            result = pearson_correlation(
                [
                    (row.observation_start, row.observation_period, float(row.value))
                    for row in left_history
                ],
                [
                    (row.observation_start, row.observation_period, float(row.value))
                    for row in right_history
                ],
                aggregate_right_quarterly=aggregate_quarterly,
            )
            alignment = (
                "monthly observations aggregated by fiscal quarter"
                if aggregate_quarterly
                else "exact calendar-month alignment"
            )
            evidence_text = (
                f"Pearson correlation between {left_code} and {right_code}: "
                f"{result['correlation']}; aligned sample size: {result['sample_size']}; "
                f"alignment: {alignment}; method: {result['method']}; "
                f"limitation: correlation does not imply causation. {result['caveat']}"
            )
            source_row = left_history[-1] if left_history else None
            input_observation_ids: list[str] = []
            for aligned_period in result["input_periods"]:
                left_periods = aligned_period["left"]
                right_periods = aligned_period["right"]
                if isinstance(left_periods, str):
                    left_periods = [left_periods]
                if isinstance(right_periods, str):
                    right_periods = [right_periods]
                input_observation_ids.extend(
                    f"obs:{left_code}:{period}" for period in left_periods
                )
                input_observation_ids.extend(
                    f"obs:{right_code}:{period}" for period in right_periods
                )
            structured.append({
                "id": f"correlation:{left_code}:{right_code}",
                "kind": "analysis",
                "title": f"Persisted-data correlation: {left_code} and {right_code}",
                "content": evidence_text,
                "source_name": (
                    f"{source_row.source_name}; ArthaSense Pearson analysis"
                    if source_row
                    else "ArthaSense Pearson analysis of persisted observations"
                ),
                "source_url": source_row.source_url if source_row else "",
                "observation_period": None,
                "publication_date": None,
                "metadata": {
                    "left_indicator": left_code,
                    "right_indicator": right_code,
                    "correlation": result["correlation"],
                    "sample_size": result["sample_size"],
                    "alignment": alignment,
                    "analysis_version": "pearson-alignment-1.0",
                    "input_observation_ids": input_observation_ids,
                },
            })
    if selected_indicator:
        history = database.get_history_range(selected_indicator, start, end, limit=10000)
        if history:
            observations: list[dict[str, object]] = [
                {
                    "observation_start": row.observation_start,
                    "observation_period": row.observation_period,
                    "value": float(row.value),
                    "source_name": row.source_name,
                    "source_url": row.source_url,
                }
                for row in history
            ]
            frequency = history[0].frequency
            series = build_growth_series(observations, frequency)
            latest = series[-1]
            values = [point["value"] for point in series]
            latest_value = latest["value"]
            if latest_value is None:
                raise ValueError("The latest persisted observation has no numeric value.")
            structured.append({
                "id": f"trend:{selected_indicator}:{latest['observation_period']}",
                "kind": "analysis",
                "title": f"Calculated {selected_indicator} trend",
                "content": (
                    f"Trend classification: {classify_trend(values)}; change direction: "
                    f"{classify_change_direction(values)}; latest value: {latest_value} "
                    f"{history[-1].unit} for {latest['observation_period']}; period change: "
                    f"{latest['period_change']}; year-on-year change: "
                    f"{latest['year_on_year_change']}; 3-period moving average: "
                    f"{latest['moving_average_3']}; 6-period moving average: "
                    f"{latest['moving_average_6']}; 12-period moving average: "
                    f"{latest['moving_average_12']}; rolling volatility: "
                    f"{latest['rolling_volatility_3']}. Calculated only from persisted "
                    f"{frequency} observations; missing periods are not filled with zero."
                ),
                "source_name": history[-1].source_name,
                "source_url": history[-1].source_url,
                "observation_period": latest["observation_period"],
                "publication_date": None,
                "metadata": {
                    "indicator_code": selected_indicator,
                    "frequency": frequency,
                    "observation_count": len(history),
                    "source_key": history[-1].source_key,
                    "analysis_version": "trend-analysis-1.0",
                    "input_observation_ids": [
                        f"obs:{selected_indicator}:{row.observation_period}"
                        for row in history[-12:]
                    ],
                },
            })
            generated_insights = generate_insights(selected_indicator, observations)
            for insight in generated_insights:
                structured.append({
                    "id": f"insight:{selected_indicator}:{insight['observation_period']}",
                    "kind": "analysis",
                    "title": f"Calculated economic insight: {insight['indicator']}",
                    "content": (
                        f"{insight['insight']} Comparison value: {insight['comparison_value']}; "
                        f"change: {insight['magnitude']} {insight['magnitude_unit']}; "
                        f"year-on-year change: {insight['year_on_year_change']}; "
                        f"classification: {insight['classification']}; trend: {insight['trend']}; "
                        f"calculation: {insight['calculation']}; interpretation: "
                        f"{insight['interpretation']}"
                    ),
                    "source_name": insight["source"],
                    "source_url": insight["source_url"],
                    "observation_period": insight["observation_period"],
                    "publication_date": None,
                    "metadata": {
                        "indicator_code": selected_indicator,
                        "evidence_strength": insight["evidence_strength"],
                        "comparison_period": insight["comparison_period"],
                        "analysis_version": "economic-insights-1.0",
                        "input_observation_ids": [
                            f"obs:{selected_indicator}:{row['observation_period']}"
                            for row in observations[-12:]
                        ],
                    },
                })

    if source:
        source_text = source.lower()
        structured = [
            item for item in structured
            if source_text in str(item["source_name"]).lower()
            or source_text in str(item["source_url"]).lower()
        ]

    query_embedding = (await embed_texts([query]))[0]
    query_terms = _tokens(query)
    chunks = database.search_research_chunks(
        indicator_code=selected_indicator,
        source=source,
        start=start,
        end=end,
    )
    document_candidates: list[tuple[float, dict[str, Any]]] = []
    for row in chunks:
        content = str(row["content"])
        lexical = len(query_terms & _tokens(f"{row['title']} {content}")) / max(len(query_terms), 1)
        raw_embedding = row["embedding"]
        embedding = _vector(raw_embedding)
        semantic = _cosine(query_embedding, embedding)
        score = 0.7 * max(0.0, semantic) + 0.3 * lexical
        metadata = _json_object(row["metadata"])
        document_candidates.append((score, {
            "id": f"document:{row['document_id']}:{row['chunk_index']}",
            "kind": "document",
            "title": f"{row['title']} (version {row['version']})",
            "content": content,
            "source_name": row["source_name"],
            "source_url": row["source_url"],
            "observation_period": None,
            "publication_date": row["publication_date"],
            "metadata": {
                **metadata,
                "document_id": str(row["document_id"]),
                "version": row["version"],
                "chunk_index": row["chunk_index"],
            },
            "_score": score,
        }))

    structured_scored: list[tuple[float, dict[str, Any]]] = []
    for item in structured:
        text = f"{item['title']} {item['content']}"
        score = len(query_terms & _tokens(text)) / max(len(query_terms), 1)
        if selected_indicator and item["metadata"].get("indicator_code") == selected_indicator:
            score += 1.0
        structured_scored.append((score, item))
    structured_scored.sort(key=lambda pair: pair[0], reverse=True)

    documents = sorted(document_candidates, key=lambda pair: pair[0], reverse=True)
    evidence: list[dict[str, Any]] = []
    # Keep both authoritative source documents and structured observations when available.
    evidence.extend(item for _, item in structured_scored[: max(1, limit - 3)])
    evidence.extend(item for _, item in documents[: min(3, limit)])
    if len(evidence) < limit:
        remainder = structured_scored[max(1, limit - 3):]
        evidence.extend(item for _, item in remainder[: limit - len(evidence)])
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        item_id = str(item["id"])
        if item_id not in seen:
            seen.add(item_id)
            item.pop("_score", None)
            unique.append(item)
        if len(unique) == limit:
            break
    return unique
