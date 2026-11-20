import math
import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ValueType = Literal["official", "calculated", "forecast", "scenario"]
Frequency = Literal["monthly", "quarterly"]
SourceStatus = Literal["LIVE", "STALE"]


def is_fiscal_year(value: str) -> bool:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    return bool(match and str(int(match.group(1)) + 1)[-2:] == match.group(2))


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(pattern=r"^[a-z0-9_-]+$")
    metric_code: str = Field(pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    frequency: Frequency
    observation_period: str = Field(min_length=1, max_length=80)
    observation_start: date
    fiscal_year: str | None = None
    quarter: str | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    value: float
    value_type: ValueType
    unit: str = Field(min_length=1, max_length=40)
    base_year: str | None = Field(default=None, max_length=20)
    source_status: SourceStatus
    last_fetched_at: datetime
    publication_date: date | None = None
    source_metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Observation values must be finite.")
        return value

    @model_validator(mode="after")
    def period_fields_must_match_frequency(self) -> "Observation":
        if self.frequency == "monthly":
            if self.month is None or self.quarter is not None:
                raise ValueError("Monthly observations require a month and cannot have a quarter.")
            if self.fiscal_year is None or not is_fiscal_year(self.fiscal_year):
                raise ValueError("Monthly observations require a valid April-March fiscal year.")
            if self.observation_start.day != 1 or self.observation_start.month != self.month:
                raise ValueError("Monthly period start must be the first day of its observation month.")
            start_year = self.observation_start.year if self.month >= 4 else self.observation_start.year - 1
            expected_fiscal_year = f"{start_year}-{str(start_year + 1)[-2:]}"
            if self.fiscal_year != expected_fiscal_year:
                raise ValueError("Monthly fiscal year does not match the observation month.")
        else:
            if self.month is not None or self.quarter not in {"Q1", "Q2", "Q3", "Q4"}:
                raise ValueError("Quarterly observations require Q1-Q4 and cannot have a month.")
            if self.fiscal_year is None or not is_fiscal_year(self.fiscal_year):
                raise ValueError("Quarterly observations require a valid fiscal year.")
            start_month = 4 + 3 * (int(self.quarter[1]) - 1)
            fiscal_start_year = int(self.fiscal_year[:4])
            expected_start = date(
                fiscal_start_year + (start_month - 1) // 12,
                (start_month - 1) % 12 + 1,
                1,
            )
            if self.observation_start != expected_start:
                raise ValueError("Quarter start does not match the fiscal year and quarter.")
        return self


class SourceFetch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(pattern=r"^[a-z0-9_-]+$")
    dataset: str = Field(min_length=1, max_length=100)
    status: SourceStatus
    last_successful_fetch: datetime
    observation_count: int = Field(ge=0)


class SourceFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(pattern=r"^[a-z0-9_-]+$")
    dataset: str = Field(min_length=1, max_length=100)
    error: str = Field(min_length=1, max_length=500)


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(default="Ministry of Statistics and Programme Implementation (MoSPI)")
    source_url: str = Field(default="https://mcp.mospi.gov.in/")
    fetches: list[SourceFetch] = Field(min_length=1)
    failed_sources: list[SourceFailure] = Field(default_factory=list)
    observations: list[Observation] = Field(min_length=1)

    @model_validator(mode="after")
    def observations_must_have_fetch_metadata(self) -> "IngestRequest":
        source_keys = {fetch.source_key for fetch in self.fetches}
        missing = {item.source_key for item in self.observations} - source_keys
        if missing:
            raise ValueError(f"Missing fetch metadata for sources: {', '.join(sorted(missing))}")
        keys = [
            (item.source_key, item.metric_code, item.observation_period)
            for item in self.observations
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate observations must be removed before ingestion.")
        fetched_keys = [fetch.source_key for fetch in self.fetches]
        failed_keys = {failure.source_key for failure in self.failed_sources}
        if (
            len(set(fetched_keys)) != len(fetched_keys)
            or len(failed_keys) != len(self.failed_sources)
            or set(fetched_keys) & failed_keys
        ):
            raise ValueError("Each source must have exactly one success or failure result.")
        return self


class IngestResponse(BaseModel):
    status: Literal["success", "partial"]
    sources: int
    observations_received: int
    observations_upserted: int
    fetched_at: datetime
    failed_sources: list[str] = Field(default_factory=list)


class StoredObservation(BaseModel):
    source_key: str
    source_name: str
    source_url: str
    metric_code: str
    name: str
    frequency: Frequency
    observation_period: str
    observation_start: date
    fiscal_year: str | None
    quarter: str | None
    month: int | None
    value: float
    value_type: ValueType
    unit: str
    base_year: str | None
    source_status: SourceStatus
    last_fetched_at: datetime


IndicatorCode = Literal[
    "gdp_real_growth",
    "cpi_inflation",
    "wpi_inflation",
    "iip_growth",
]
ForecastModel = Literal[
    "naive",
    "seasonal_naive",
    "arima",
    "sarima",
    "random_forest",
    "xgboost",
]


class ForecastGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_code: IndicatorCode
    model: ForecastModel = "naive"
    horizon: int = Field(default=3, ge=1, le=12)
    persist: bool = True

    @model_validator(mode="after")
    def horizon_must_match_frequency(self) -> "ForecastGenerateRequest":
        if self.indicator_code == "gdp_real_growth":
            if self.horizon not in {1, 2, 4}:
                raise ValueError("GDP forecast horizon must be 1, 2 or 4 quarters.")
        elif self.horizon not in {1, 3, 6, 12}:
            raise ValueError("Monthly forecast horizon must be 1, 3, 6 or 12 months.")
        return self


class ForecastMetricsResponse(BaseModel):
    mae: float | None
    rmse: float | None
    smape: float | None
    directional_accuracy: float | None
    test_observations: int
    test_period_start: date | None
    test_period_end: date | None
    method: str


class ForecastPointResponse(BaseModel):
    observation_period: str
    observation_start: date
    horizon: int
    value: float
    lower_bound: float | None
    upper_bound: float | None


class ForecastGenerateResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    indicator_code: IndicatorCode
    model: ForecastModel
    model_version: str
    status: Literal["success", "insufficient_data", "failed"]
    warning: str | None = None
    training_observation_count: int
    training_period_start: date | None
    training_period_end: date | None
    metrics: ForecastMetricsResponse | None
    forecasts: list[ForecastPointResponse]
    persisted: bool


class SavedForecastResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    indicator_code: str
    model: str
    model_version: str
    observation_period: str
    observation_start: date
    horizon: int
    value: float
    lower_bound: float | None
    upper_bound: float | None
    unit: str
    generated_at: datetime
    training_period_start: date | None
    training_period_end: date | None


class ModelComparisonResponse(BaseModel):
    indicator_code: IndicatorCode
    models: list[dict[str, object]]


class HistoricalVersusForecastResponse(BaseModel):
    indicator_code: IndicatorCode
    model: ForecastModel
    historical: list[StoredObservation]
    forecasts: list[ForecastPointResponse]


AnalysisIndicator = Literal[
    "gdp_real_growth",
    "gva_agriculture",
    "gva_industry",
    "gva_services",
    "cpi_inflation",
    "wpi_inflation",
    "iip_growth",
]


class AnalysisPoint(BaseModel):
    observation_start: date
    observation_period: str
    value: float
    period_change: float | None
    year_on_year_change: float | None
    year_on_year_percent_change: float | None
    moving_average_3: float | None
    moving_average_6: float | None
    moving_average_12: float | None
    rolling_volatility_3: float | None
    deviation_from_ma: float | None


class TrendAnalysisResponse(BaseModel):
    indicator_code: AnalysisIndicator
    frequency: Frequency
    observation_count: int
    sample_start: date | None
    sample_end: date | None
    trend: str
    change_direction: str
    latest: AnalysisPoint | None
    series: list[AnalysisPoint]
    methodology: str


class GrowthAnalysisResponse(BaseModel):
    indicator_code: AnalysisIndicator
    frequency: Frequency
    observation_count: int
    series: list[AnalysisPoint]
    methodology: str


class VolatilityResponse(BaseModel):
    indicator_code: AnalysisIndicator
    frequency: Frequency
    window: int
    observation_count: int
    historical_min: float | None
    historical_max: float | None
    rolling_values: list[dict[str, object]]
    methodology: str


class CorrelationResponse(BaseModel):
    left_indicator: AnalysisIndicator
    right_indicator: AnalysisIndicator
    correlation: float | None
    sample_size: int
    method: str
    alignment: str
    caveat: str


class EconomicInsightResponse(BaseModel):
    indicator_code: AnalysisIndicator
    indicator: str
    observation_period: str
    observation_start: date
    actual_value: float
    comparison_period: str
    comparison_value: float
    magnitude: float
    magnitude_unit: str
    year_on_year_change: float | None
    classification: Literal["positive", "negative", "neutral"]
    evidence_strength: Literal["high", "limited"]
    trend: str
    calculation: str
    insight: str
    source: str
    source_url: str
    interpretation: str


class SectorAnalysisResponse(BaseModel):
    sectors: list[dict[str, object]]
    methodology: str


AnomalyIndicator = Literal[
    "gdp_real_growth",
    "gva_agriculture",
    "gva_industry",
    "gva_services",
    "cpi_inflation",
    "wpi_inflation",
    "iip_growth",
]
AnomalyMethod = Literal["zscore", "rolling", "isolation_forest", "seasonal_residual"]
AnomalySeverity = Literal["low", "medium", "high"]


class AnomalyDetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_code: AnomalyIndicator
    methods: list[AnomalyMethod] = Field(default_factory=lambda: ["zscore", "rolling"])
    threshold: float = Field(default=2.5, ge=1.0, le=6.0)
    rolling_window: int = Field(default=12, ge=3, le=60)
    contamination: float = Field(default=0.05, gt=0.0, lt=0.5)
    start: date | None = None
    end: date | None = None
    persist: bool = True

    @model_validator(mode="after")
    def date_range_must_be_valid(self) -> "AnomalyDetectRequest":
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start must be before or equal to end.")
        if len(set(self.methods)) != len(self.methods):
            raise ValueError("Duplicate detection methods are not allowed.")
        return self


class AnomalyResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    indicator_code: str
    indicator_name: str
    observation_period: str
    observation_start: date
    actual_value: float
    expected_value: float
    absolute_deviation: float
    percentage_deviation: float | None
    anomaly_score: float
    detection_method: AnomalyMethod
    severity: AnomalySeverity
    detected_at: datetime
    source_key: str | None
    source_name: str | None
    source_url: str | None
    model_version: str
    model_parameters: dict[str, object]
    explanation: str


class AnomalyDetectResponse(BaseModel):
    indicator_code: AnomalyIndicator
    observation_count: int
    detected_count: int
    persisted_count: int
    methods: list[AnomalyMethod]
    anomalies: list[AnomalyResponse]


class AnomalySummaryResponse(BaseModel):
    total: int
    low: int
    medium: int
    high: int
    by_indicator: dict[str, int]


class ResearchChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank.")
        return normalized


class ResearchEvidence(BaseModel):
    id: str
    kind: Literal["observation", "forecast", "analysis", "anomaly", "document"]
    title: str
    content: str
    source_name: str
    source_url: str
    observation_period: str | None = None
    publication_date: date | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ResearchChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list[ResearchEvidence]
    generated_at: datetime


class ResearchMessageResponse(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    citations: list[ResearchEvidence] = Field(default_factory=list)
    created_at: datetime


class ResearchConversationResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ResearchMessageResponse] = Field(default_factory=list)


class ResearchRetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    indicator_code: AnalysisIndicator | None = None
    source: str | None = Field(default=None, max_length=200)
    start: date | None = None
    end: date | None = None
    limit: int = Field(default=8, ge=1, le=20)

    @model_validator(mode="after")
    def valid_date_range(self) -> "ResearchRetrieveRequest":
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("query must not be blank.")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must be on or before end.")
        return self


class ResearchDocumentMetadata(BaseModel):
    id: str
    title: str
    source_name: str
    source_url: str
    publication_date: date | None
    version: str
    content_sha256: str
    created_at: datetime


class ResearchSourceResponse(BaseModel):
    source_name: str
    source_url: str
    source_type: Literal["economic_data", "document"]
    latest_observation: date | None = None
    publication_date: date | None = None
