import hmac
import logging
import os
import uuid
from datetime import date
from typing import get_args

import psycopg
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile

from . import database
from .forecasting import generate_model_forecast
from .trend_analysis import build_growth_series, rolling_volatility, trend_summary
from .correlation_analysis import pearson_correlation
from .economic_insights import generate_insights
from .anomaly_detection import (
    isolation_forest_detection,
    seasonal_residual_detection,
    zscore_detection,
)
from .schemas import (
    ForecastGenerateRequest,
    ForecastGenerateResponse,
    ForecastMetricsResponse,
    ForecastPointResponse,
    HistoricalVersusForecastResponse,
    IngestRequest,
    IngestResponse,
    ModelComparisonResponse,
    SavedForecastResponse,
    StoredObservation,
    AnalysisIndicator,
    AnalysisPoint,
    TrendAnalysisResponse,
    GrowthAnalysisResponse,
    VolatilityResponse,
    CorrelationResponse,
    EconomicInsightResponse,
    SectorAnalysisResponse,
    AnomalyDetectRequest,
    AnomalyDetectResponse,
    AnomalyResponse,
    AnomalySummaryResponse,
    ResearchChatRequest,
    ResearchChatResponse,
    ResearchConversationResponse,
    ResearchDocumentMetadata,
    ResearchEvidence,
    ResearchRetrieveRequest,
    ResearchSourceResponse,
)
from .document_ingestion import (
    MAX_DOCUMENT_BYTES,
    chunk_text,
    document_sha256,
    extract_document_text,
    validate_official_source_url,
)
from .embedding_service import EmbeddingProviderError, embed_texts
from .llm_provider import LLMProviderError
from .research_assistant import answer_research_question
from .retrieval_service import retrieve_evidence


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("arthasense.intelligence")

app = FastAPI(
    title="ArthaSense Intelligence Service",
    version="1.0.0",
    description="Optional persistence and validated economic-intelligence services.",
)


def require_service_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("INTELLIGENCE_API_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="INTELLIGENCE_API_TOKEN is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required.")
    provided = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid bearer token.")


def require_research_owner(owner: str = Header(alias="X-Research-Owner")) -> uuid.UUID:
    try:
        return uuid.UUID(owner)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="A valid research session is required.") from error


def require_document_ingest_token(
    ingestion_token: str | None = Header(default=None, alias="X-Research-Ingest-Token"),
) -> None:
    expected = os.getenv("RESEARCH_INGEST_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Document ingestion is not configured.")
    if not ingestion_token or not hmac.compare_digest(expected, ingestion_token):
        raise HTTPException(status_code=401, detail="Document ingestion token is invalid.")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "databaseConfigured": database.get_database_url() is not None,
        "serviceTokenConfigured": bool(os.getenv("INTELLIGENCE_API_TOKEN")),
    }


@app.post(
    "/v1/research/chat",
    response_model=ResearchChatResponse,
    dependencies=[Depends(require_service_token)],
)
async def research_chat(
    payload: ResearchChatRequest,
    owner_id: uuid.UUID = Depends(require_research_owner),
) -> ResearchChatResponse:
    try:
        result = await answer_research_question(
            owner_id=owner_id,
            question=payload.question.strip(),
            conversation_id=payload.conversation_id,
        )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (EmbeddingProviderError, LLMProviderError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail=f"Grounded response validation failed: {error}") from error
    except (RuntimeError, psycopg.Error) as error:
        logger.exception("Research assistant request failed")
        raise HTTPException(status_code=503, detail="Research evidence storage is unavailable.") from error
    return ResearchChatResponse.model_validate(result)


@app.get(
    "/v1/research/history",
    response_model=list[ResearchConversationResponse],
    dependencies=[Depends(require_service_token)],
)
def research_history(
    owner_id: uuid.UUID = Depends(require_research_owner),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[ResearchConversationResponse]:
    try:
        rows = database.get_research_conversations(owner_id, limit)
    except (RuntimeError, psycopg.Error) as error:
        logger.exception("Research conversation history query failed")
        raise HTTPException(status_code=503, detail="Research history is unavailable.") from error
    return [ResearchConversationResponse.model_validate(row) for row in rows]


@app.post(
    "/v1/research/retrieve",
    response_model=list[ResearchEvidence],
    dependencies=[Depends(require_service_token)],
)
async def research_retrieve(payload: ResearchRetrieveRequest) -> list[ResearchEvidence]:
    try:
        evidence = await retrieve_evidence(
            payload.query,
            indicator_code=payload.indicator_code,
            source=payload.source,
            start=payload.start,
            end=payload.end,
            limit=payload.limit,
        )
    except EmbeddingProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (RuntimeError, psycopg.Error) as error:
        logger.exception("Research retrieval failed")
        raise HTTPException(status_code=503, detail="Research retrieval is unavailable.") from error
    return [ResearchEvidence.model_validate(item) for item in evidence]


@app.post(
    "/v1/research/documents/ingest",
    response_model=ResearchDocumentMetadata,
    dependencies=[Depends(require_service_token), Depends(require_document_ingest_token)],
)
async def research_document_ingest(
    file: UploadFile = File(...),
    title: str = Form(min_length=1, max_length=300),
    source_name: str = Form(min_length=1, max_length=200),
    source_url: str = Form(min_length=1, max_length=2048),
    version: str = Form(min_length=1, max_length=80),
    publication_date: date | None = Form(default=None),
    indicator_code: str | None = Form(default=None, max_length=80),
) -> ResearchDocumentMetadata:
    try:
        if not title.strip() or not source_name.strip() or not version.strip():
            raise ValueError("title, source_name and version must not be blank.")
        if indicator_code is not None and indicator_code not in get_args(AnalysisIndicator):
            raise ValueError("indicator_code is not supported.")
        validate_official_source_url(source_url)
        payload = await file.read(MAX_DOCUMENT_BYTES + 1)
        text, content_type = extract_document_text(file.filename or "", file.content_type or "", payload)
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("No searchable text was found in the document.")
        embeddings = await embed_texts(chunks)
        document, _ = database.persist_research_document(
            document_id=uuid.uuid4(),
            title=title.strip(),
            source_name=source_name.strip(),
            source_url=source_url,
            publication_date=publication_date,
            version=version.strip(),
            content_sha256=document_sha256(payload),
            content_type=content_type,
            metadata={"indicator_code": indicator_code} if indicator_code else {},
            chunks=chunks,
            embeddings=embeddings,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EmbeddingProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (RuntimeError, psycopg.Error) as error:
        logger.exception("Research document persistence failed")
        raise HTTPException(status_code=503, detail="Document storage is unavailable.") from error
    finally:
        await file.close()
    return ResearchDocumentMetadata.model_validate(document)


@app.get(
    "/v1/research/documents",
    response_model=list[ResearchDocumentMetadata],
    dependencies=[Depends(require_service_token)],
)
def research_documents(
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ResearchDocumentMetadata]:
    try:
        rows = database.list_research_documents(limit)
    except (RuntimeError, psycopg.Error) as error:
        logger.exception("Research document listing failed")
        raise HTTPException(status_code=503, detail="Document listing is unavailable.") from error
    return [ResearchDocumentMetadata.model_validate(row) for row in rows]


@app.get(
    "/v1/research/sources",
    response_model=list[ResearchSourceResponse],
    dependencies=[Depends(require_service_token)],
)
def research_sources() -> list[ResearchSourceResponse]:
    try:
        rows = database.get_research_sources()
    except (RuntimeError, psycopg.Error) as error:
        logger.exception("Research source listing failed")
        raise HTTPException(status_code=503, detail="Source listing is unavailable.") from error
    return [
        ResearchSourceResponse(
            source_name=row["source_name"],
            source_url=row["source_url"],
            source_type=row["source_type"],
            latest_observation=row["latest_observation"],
            publication_date=row["publication_date"],
        )
        for row in rows
    ]


@app.post("/v1/ingest", response_model=IngestResponse, dependencies=[Depends(require_service_token)])
def ingest_official_data(payload: IngestRequest) -> IngestResponse:
    try:
        upserted = database.ingest(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except psycopg.Error as error:
        logger.exception("Official-data persistence failed")
        raise HTTPException(status_code=503, detail="PostgreSQL ingestion failed.") from error

    return IngestResponse(
        status="success"
        if not payload.failed_sources and all(fetch.status == "LIVE" for fetch in payload.fetches)
        else "partial",
        sources=len(payload.fetches),
        observations_received=len(payload.observations),
        observations_upserted=upserted,
        fetched_at=max(fetch.last_successful_fetch for fetch in payload.fetches),
        failed_sources=[failure.source_key for failure in payload.failed_sources],
    )


@app.get(
    "/v1/history/{metric_code}",
    response_model=list[StoredObservation],
    dependencies=[Depends(require_service_token)],
)
def history(
    metric_code: str,
    limit: int = Query(default=1000, ge=1, le=10000),
) -> list[StoredObservation]:
    try:
        return database.get_history(metric_code, limit)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except psycopg.Error as error:
        logger.exception("Historical-data query failed for %s", metric_code)
        raise HTTPException(status_code=503, detail="PostgreSQL history query failed.") from error


@app.post(
    "/v1/forecasts/generate",
    response_model=ForecastGenerateResponse,
    dependencies=[Depends(require_service_token)],
)
def generate_forecast(payload: ForecastGenerateRequest) -> ForecastGenerateResponse:
    try:
        history = database.get_history(payload.indicator_code, limit=10000)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except psycopg.Error as error:
        logger.exception("Forecast history query failed")
        raise HTTPException(status_code=503, detail="PostgreSQL history query failed.") from error

    values = [
        (item.observation_start, item.observation_period, float(item.value))
        for item in history
    ]
    result = generate_model_forecast(
        values,
        payload.indicator_code,
        payload.model,
        payload.horizon,
    )

    metrics = (
        ForecastMetricsResponse(
            mae=result.metrics.mae,
            rmse=result.metrics.rmse,
            smape=result.metrics.smape,
            directional_accuracy=result.metrics.directional_accuracy,
            test_observations=result.metrics.test_observations,
            test_period_start=result.metrics.test_period_start,
            test_period_end=result.metrics.test_period_end,
            method=result.metrics.method,
        )
        if result.metrics is not None
        else None
    )

    persisted = False
    if payload.persist:
        try:
            persisted = database.persist_forecast(
                indicator_code=payload.indicator_code,
                model_name=result.model_name,
                model_version=result.model_version,
                status=result.status,
                warning=result.warning,
                training_period_start=values[0][0] if values else None,
                training_period_end=values[-1][0] if values else None,
                observations_used=len(values),
                metrics=result.metrics,
                forecasts=result.forecasts,
            )
        except psycopg.Error as error:
            logger.exception("Forecast persistence failed")
            raise HTTPException(status_code=503, detail="PostgreSQL forecast write failed.") from error

    return ForecastGenerateResponse(
        indicator_code=payload.indicator_code,
        model=result.model_name,
        model_version=result.model_version,
        status=result.status,
        warning=result.warning,
        training_observation_count=len(values),
        training_period_start=values[0][0] if values else None,
        training_period_end=values[-1][0] if values else None,
        metrics=metrics,
        forecasts=[
            ForecastPointResponse(
                observation_period=point.observation_period,
                observation_start=point.observation_start,
                horizon=point.horizon,
                value=point.value,
                lower_bound=point.lower_bound,
                upper_bound=point.upper_bound,
            )
            for point in result.forecasts
        ],
        persisted=persisted,
    )


@app.get(
    "/v1/forecasts/{indicator_code}",
    response_model=list[SavedForecastResponse],
    dependencies=[Depends(require_service_token)],
)
def saved_forecasts(
    indicator_code: str,
    model: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[SavedForecastResponse]:
    if indicator_code not in {
        "gdp_real_growth",
        "cpi_inflation",
        "wpi_inflation",
        "iip_growth",
    }:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    try:
        rows = database.get_saved_forecasts(indicator_code, model, limit)
    except psycopg.Error as error:
        logger.exception("Saved forecast query failed")
        raise HTTPException(status_code=503, detail="PostgreSQL forecast query failed.") from error
    return [SavedForecastResponse.model_validate(row) for row in rows]


@app.get(
    "/v1/forecasts/{indicator_code}/compare",
    response_model=ModelComparisonResponse,
    dependencies=[Depends(require_service_token)],
)
def forecast_comparison(indicator_code: str) -> ModelComparisonResponse:
    if indicator_code not in {
        "gdp_real_growth",
        "cpi_inflation",
        "wpi_inflation",
        "iip_growth",
    }:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    try:
        rows = database.get_model_comparison(indicator_code)
    except psycopg.Error as error:
        logger.exception("Forecast comparison query failed")
        raise HTTPException(status_code=503, detail="PostgreSQL comparison query failed.") from error
    return ModelComparisonResponse(indicator_code=indicator_code, models=rows)


@app.get(
    "/v1/forecasts/{indicator_code}/history-versus-forecast",
    response_model=HistoricalVersusForecastResponse,
    dependencies=[Depends(require_service_token)],
)
def history_vs_forecast(
    indicator_code: str,
    model: str = Query(default="naive"),
    limit: int = Query(default=100, ge=1, le=1000),
) -> HistoricalVersusForecastResponse:
    if indicator_code not in {
        "gdp_real_growth",
        "cpi_inflation",
        "wpi_inflation",
        "iip_growth",
    }:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    if model not in {
        "naive",
        "seasonal_naive",
        "arima",
        "sarima",
        "random_forest",
        "xgboost",
    }:
        raise HTTPException(status_code=422, detail="Unknown forecast model.")
    try:
        history = database.get_history(indicator_code, limit=limit)
        rows = database.get_saved_forecasts(indicator_code, model, limit)
    except psycopg.Error as error:
        logger.exception("Historical-versus-forecast query failed")
        raise HTTPException(status_code=503, detail="PostgreSQL forecast query failed.") from error
    forecasts = [
        ForecastPointResponse(
            observation_period=row["observation_period"],
            observation_start=row["observation_start"],
            horizon=row["horizon"],
            value=float(row["value"]),
            lower_bound=None if row["lower_bound"] is None else float(row["lower_bound"]),
            upper_bound=None if row["upper_bound"] is None else float(row["upper_bound"]),
        )
        for row in rows
    ]
    return HistoricalVersusForecastResponse(
        indicator_code=indicator_code,
        model=model,
        historical=history,
        forecasts=forecasts,
    )


ANALYSIS_INDICATORS = {
    "gdp_real_growth",
    "gva_agriculture",
    "gva_industry",
    "gva_services",
    "cpi_inflation",
    "wpi_inflation",
    "iip_growth",
}


def _frequency_for_indicator(indicator_code: str) -> str:
    return "quarterly" if indicator_code in {"gdp_real_growth", "gva_agriculture", "gva_industry", "gva_services"} else "monthly"


def _analysis_series(indicator_code: str, start: str | None, end: str | None):
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    history = database.get_history_range(indicator_code, start_date, end_date, limit=10000)
    observations = [
        {
            "observation_start": item.observation_start,
            "observation_period": item.observation_period,
            "value": float(item.value),
            "source_name": item.source_name,
            "source_url": item.source_url,
        }
        for item in history
    ]
    return history, observations


@app.get(
    "/v1/analysis/trends/{indicator_code}",
    response_model=TrendAnalysisResponse,
    dependencies=[Depends(require_service_token)],
)
def analysis_trends(
    indicator_code: str,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> TrendAnalysisResponse:
    if indicator_code not in ANALYSIS_INDICATORS:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    try:
        history, observations = _analysis_series(indicator_code, start, end)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="PostgreSQL analysis query failed.") from error

    frequency = _frequency_for_indicator(indicator_code)
    series = build_growth_series(observations, frequency)
    summary = trend_summary(series)
    latest = (
        AnalysisPoint.model_validate(summary["latest"])
        if summary["latest"] is not None
        else None
    )
    return TrendAnalysisResponse(
        indicator_code=indicator_code,
        frequency=frequency,
        observation_count=len(series),
        sample_start=history[0].observation_start if history else None,
        sample_end=history[-1].observation_start if history else None,
        trend=str(summary["trend"]),
        change_direction=str(summary["change_direction"]),
        latest=latest,
        series=[AnalysisPoint.model_validate(point) for point in series],
        methodology=(
            "Linear trend over the latest six available observations; "
            "upward/downward threshold is 0.15 percentage points per period; "
            "missing observations are excluded."
        ),
    )


@app.get(
    "/v1/analysis/growth/{indicator_code}",
    response_model=GrowthAnalysisResponse,
    dependencies=[Depends(require_service_token)],
)
def analysis_growth(
    indicator_code: str,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> GrowthAnalysisResponse:
    if indicator_code not in ANALYSIS_INDICATORS:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    try:
        _, observations = _analysis_series(indicator_code, start, end)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="PostgreSQL analysis query failed.") from error
    frequency = _frequency_for_indicator(indicator_code)
    series = build_growth_series(observations, frequency)
    return GrowthAnalysisResponse(
        indicator_code=indicator_code,
        frequency=frequency,
        observation_count=len(series),
        series=[AnalysisPoint.model_validate(point) for point in series],
        methodology=(
            "Period change and year-on-year change are percentage-point differences "
            "between values. Year-on-year percentage change uses (current/prior - 1)*100 "
            "and is unavailable when the prior value is missing or zero."
        ),
    )


@app.get(
    "/v1/analysis/volatility/{indicator_code}",
    response_model=VolatilityResponse,
    dependencies=[Depends(require_service_token)],
)
def analysis_volatility(
    indicator_code: str,
    window: int = Query(default=3, ge=2, le=12),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> VolatilityResponse:
    if indicator_code not in ANALYSIS_INDICATORS:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    try:
        _, observations = _analysis_series(indicator_code, start, end)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="PostgreSQL analysis query failed.") from error
    values = [float(row["value"]) for row in observations]
    rolling = rolling_volatility(values, window)
    finite = [value for value in values if value is not None]
    return VolatilityResponse(
        indicator_code=indicator_code,
        frequency=_frequency_for_indicator(indicator_code),
        window=window,
        observation_count=len(values),
        historical_min=min(finite) if finite else None,
        historical_max=max(finite) if finite else None,
        rolling_values=[
            {
                "observation_start": row["observation_start"],
                "observation_period": row["observation_period"],
                "value": row["value"],
                "rolling_volatility": rolling[index],
            }
            for index, row in enumerate(observations)
        ],
        methodology=(
            f"Historical range and sample rolling standard deviation over {window} "
            "available observations; missing observations do not become zeros."
        ),
    )


@app.get(
    "/v1/analysis/correlations",
    dependencies=[Depends(require_service_token)],
)
def analysis_correlations(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> list[CorrelationResponse]:
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    pairs = [
        ("gdp_real_growth", "iip_growth", True),
        ("cpi_inflation", "wpi_inflation", False),
        ("gdp_real_growth", "cpi_inflation", True),
        ("iip_growth", "wpi_inflation", False),
    ]
    results: list[CorrelationResponse] = []
    for left_code, right_code, aggregate_quarterly in pairs:
        try:
            left_history = database.get_history_range(left_code, start_date, end_date, limit=10000)
            right_history = database.get_history_range(right_code, start_date, end_date, limit=10000)
        except psycopg.Error as error:
            raise HTTPException(status_code=503, detail="PostgreSQL correlation query failed.") from error
        left = [
            (row.observation_start, row.observation_period, float(row.value))
            for row in left_history
        ]
        right = [
            (row.observation_start, row.observation_period, float(row.value))
            for row in right_history
        ]
        result = pearson_correlation(
            left,
            right,
            aggregate_right_quarterly=aggregate_quarterly,
        )
        alignment = (
            "IIP monthly mean aggregated to fiscal quarter"
            if aggregate_quarterly and left_code == "gdp_real_growth"
            else "CPI monthly observations aligned to fiscal quarter"
            if aggregate_quarterly
            else "Exact calendar-month alignment"
        )
        results.append(
            CorrelationResponse(
                left_indicator=left_code,
                right_indicator=right_code,
                correlation=result["correlation"],
                sample_size=int(result["sample_size"]),
                method=str(result["method"]),
                alignment=alignment,
                caveat=str(result["caveat"]),
            )
        )
    return results


@app.get(
    "/v1/analysis/insights",
    response_model=list[EconomicInsightResponse],
    dependencies=[Depends(require_service_token)],
)
def analysis_insights(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> list[EconomicInsightResponse]:
    insights: list[EconomicInsightResponse] = []
    for indicator_code in ("gdp_real_growth", "cpi_inflation", "wpi_inflation", "iip_growth"):
        try:
            history, observations = _analysis_series(indicator_code, start, end)
        except psycopg.Error as error:
            raise HTTPException(status_code=503, detail="PostgreSQL insight query failed.") from error
        for insight in generate_insights(indicator_code, observations):
            if not insight["source"]:
                continue
            insights.append(EconomicInsightResponse.model_validate(insight))
    return insights


@app.get(
    "/v1/analysis/sectors",
    response_model=SectorAnalysisResponse,
    dependencies=[Depends(require_service_token)],
)
def analysis_sectors(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> SectorAnalysisResponse:
    sectors: list[dict[str, object]] = []
    for indicator_code, sector_name in (
        ("gva_agriculture", "Agriculture"),
        ("gva_industry", "Industry"),
        ("gva_services", "Services"),
    ):
        try:
            history, observations = _analysis_series(indicator_code, start, end)
        except psycopg.Error as error:
            raise HTTPException(status_code=503, detail="PostgreSQL sector query failed.") from error
        if not observations:
            continue
        series = build_growth_series(observations, "quarterly")
        summary = trend_summary(series)
        sectors.append(
            {
                "sector": sector_name,
                "indicator_code": indicator_code,
                "observation_count": len(series),
                "latest": summary["latest"],
                "trend": summary["trend"],
                "change_direction": summary["change_direction"],
                "source": history[-1].source_name if history else "MoSPI",
                "source_url": history[-1].source_url if history else "https://mcp.mospi.gov.in/",
                "provenance": "Official or derived GVA metric as marked by existing ingestion",
            }
        )
    return SectorAnalysisResponse(
        sectors=sectors,
        methodology=(
            "Quarterly period comparisons use available official or derived GVA observations "
            "persisted by the existing ingestion pipeline; manufacturing is omitted unless "
            "a dedicated official metric is persisted."
        ),
    )


ANOMALY_INDICATORS = {
    "gdp_real_growth",
    "gva_agriculture",
    "gva_industry",
    "gva_services",
    "cpi_inflation",
    "wpi_inflation",
    "iip_growth",
}


@app.post(
    "/v1/anomalies/detect",
    response_model=AnomalyDetectResponse,
    dependencies=[Depends(require_service_token)],
)
def detect_anomalies(payload: AnomalyDetectRequest) -> AnomalyDetectResponse:
    if payload.indicator_code not in ANOMALY_INDICATORS:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    try:
        history = database.get_history_range(
            payload.indicator_code,
            payload.start,
            payload.end,
            limit=10000,
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="PostgreSQL anomaly query failed.") from error

    observations = [
        {
            "observation_start": item.observation_start,
            "observation_period": item.observation_period,
            "value": float(item.value),
            "source_key": item.source_key,
            "source_name": item.source_name,
            "source_url": item.source_url,
        }
        for item in history
    ]
    frequency = "quarterly" if payload.indicator_code in {
        "gdp_real_growth",
        "gva_agriculture",
        "gva_industry",
        "gva_services",
    } else "monthly"

    detected = []
    if "zscore" in payload.methods:
        detected.extend(zscore_detection(observations, payload.threshold))
    if "rolling" in payload.methods:
        detected.extend(
            zscore_detection(
                observations,
                payload.threshold,
                rolling_window=payload.rolling_window,
            )
        )
    if "isolation_forest" in payload.methods:
        detected.extend(
            isolation_forest_detection(
                observations,
                contamination=payload.contamination,
            )
        )
    if "seasonal_residual" in payload.methods:
        detected.extend(
            seasonal_residual_detection(
                observations,
                frequency,
                threshold=payload.threshold,
            )
        )

    persisted_count = 0
    if payload.persist:
        try:
            persisted_count = database.persist_anomalies(
                detected,
                indicator_code=payload.indicator_code,
                model_parameters={
                    "threshold": payload.threshold,
                    "rolling_window": payload.rolling_window,
                    "contamination": payload.contamination,
                    "frequency": frequency,
                },
            )
        except psycopg.Error as error:
            raise HTTPException(status_code=503, detail="PostgreSQL anomaly write failed.") from error

    return AnomalyDetectResponse(
        indicator_code=payload.indicator_code,
        observation_count=len(observations),
        detected_count=len(detected),
        persisted_count=persisted_count,
        methods=payload.methods,
        anomalies=[
            AnomalyResponse(
                indicator_code=payload.indicator_code,
                indicator_name=(
                    history[0].name
                    if history
                    else payload.indicator_code
                ),
                observation_period=item.observation_period,
                observation_start=item.observation_start,
                actual_value=item.actual_value,
                expected_value=item.expected_value,
                absolute_deviation=item.absolute_deviation,
                percentage_deviation=item.percentage_deviation,
                anomaly_score=item.anomaly_score,
                detection_method=item.detection_method,
                severity=item.severity,
                detected_at=item.detected_at,
                source_key=item.source_key,
                source_name=item.source_name,
                source_url=item.source_url,
                model_version=item.model_version,
                model_parameters={
                    "threshold": payload.threshold,
                    "rolling_window": payload.rolling_window,
                    "contamination": payload.contamination,
                    "frequency": frequency,
                },
                explanation=item.explanation,
            )
            for item in detected
        ],
    )


@app.get(
    "/v1/anomalies",
    response_model=list[AnomalyResponse],
    dependencies=[Depends(require_service_token)],
)
def list_anomalies(
    indicator_code: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    method: str | None = Query(default=None),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AnomalyResponse]:
    if severity not in {None, "low", "medium", "high"}:
        raise HTTPException(status_code=422, detail="severity must be low, medium or high.")
    if method not in {None, "zscore", "rolling", "isolation_forest", "seasonal_residual"}:
        raise HTTPException(status_code=422, detail="Unknown detection method.")
    if indicator_code and indicator_code not in ANOMALY_INDICATORS:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start must be before or equal to end.")
    try:
        rows = database.get_anomalies(
            indicator_code=indicator_code,
            severity=severity,
            method=method,
            start=start,
            end=end,
            limit=limit,
        )
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="PostgreSQL anomaly query failed.") from error

    results = []
    for row in rows:
        results.append(
            AnomalyResponse(
                indicator_code=row["indicator_code"],
                indicator_name=row["indicator_name"],
                observation_period=row["observation_period"],
                observation_start=date.fromisoformat(str(row["observation_start"])),
                actual_value=float(row["actual_value"]),
                expected_value=float(row["expected_value"]),
                absolute_deviation=float(row["absolute_deviation"]),
                percentage_deviation=(
                    None
                    if row["percentage_deviation"] is None
                    else float(row["percentage_deviation"])
                ),
                anomaly_score=float(row["anomaly_score"]),
                detection_method=row["detection_method"],
                severity=row["severity"],
                detected_at=row["detected_at"],
                source_key=row["source_key"],
                source_name=row["source_name"],
                source_url=row["source_url"],
                model_version=row["model_version"],
                model_parameters=dict(row["model_parameters"] or {}),
                explanation=row["explanation"],
            )
        )
    return results


@app.get(
    "/v1/anomalies/summary",
    response_model=AnomalySummaryResponse,
    dependencies=[Depends(require_service_token)],
)
def anomaly_summary() -> AnomalySummaryResponse:
    try:
        summary = database.get_anomaly_summary()
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="PostgreSQL anomaly summary failed.") from error
    return AnomalySummaryResponse.model_validate(summary)


@app.get(
    "/v1/anomalies/methods",
    dependencies=[Depends(require_service_token)],
)
def anomaly_methods() -> dict[str, object]:
    return {
        "methods": [
            {
                "code": "zscore",
                "name": "Historical Z-score",
                "minimum_observations": 3,
                "severity": "low 1.25x threshold, medium 1.25-1.5x, high >=1.5x",
            },
            {
                "code": "rolling",
                "name": "Rolling-window Z-score",
                "minimum_observations": "At least 3 prior observations",
                "severity": "low 1.25x threshold, medium 1.25-1.5x, high >=1.5x",
            },
            {
                "code": "isolation_forest",
                "name": "Isolation Forest",
                "minimum_observations": 15,
                "severity": "low 0.05-0.10, medium 0.10-0.15, high >=0.15",
            },
            {
                "code": "seasonal_residual",
                "name": "Seasonal residual Z-score",
                "minimum_observations": "Three complete cycles",
                "severity": "low 1.25x threshold, medium 1.25-1.5x, high >=1.5x",
            },
        ],
        "caveat": "Statistical anomalies are not verified economic events or causal claims.",
    }


@app.get(
    "/v1/anomalies/{indicator_code}",
    response_model=list[AnomalyResponse],
    dependencies=[Depends(require_service_token)],
)
def list_indicator_anomalies(
    indicator_code: str,
    severity: str | None = Query(default=None),
    method: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AnomalyResponse]:
    if indicator_code not in ANOMALY_INDICATORS:
        raise HTTPException(status_code=422, detail="Unknown indicator code.")
    return list_anomalies(
        indicator_code=indicator_code,
        severity=severity,
        method=method,
        limit=limit,
    )
