from datetime import date, datetime, timezone

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas import IngestRequest, Observation, is_fiscal_year


def observation(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "source_key": "cpi",
        "metric_code": "cpi_general_index",
        "name": "CPI General index",
        "frequency": "monthly",
        "observation_period": "Jan 2026",
        "observation_start": date(2026, 1, 1),
        "fiscal_year": "2025-26",
        "month": 1,
        "value": 108.2,
        "value_type": "official",
        "unit": "index",
        "base_year": "2024",
        "source_status": "LIVE",
        "last_fetched_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
        "publication_date": None,
        "source_metadata": {},
    }
    return {**values, **overrides}


def test_fiscal_year_validation_spans_april_to_march() -> None:
    assert is_fiscal_year("2025-26")
    assert not is_fiscal_year("2025-25")
    Observation.model_validate(observation())
    with pytest.raises(ValidationError, match="fiscal year does not match"):
        Observation.model_validate(observation(fiscal_year="2026-27"))


def test_quarter_observation_starts_at_correct_fiscal_month() -> None:
    quarter = observation(
        source_key="nas",
        metric_code="gdp_real_growth",
        name="Real GDP growth",
        frequency="quarterly",
        observation_period="Q4 FY 2025-26",
        observation_start=date(2026, 1, 1),
        fiscal_year="2025-26",
        quarter="Q4",
        month=None,
        unit="%",
        base_year="2011-12",
    )
    Observation.model_validate(quarter)
    with pytest.raises(ValidationError, match="Quarter start"):
        Observation.model_validate({**quarter, "observation_start": date(2025, 10, 1)})


def test_ingestion_rejects_duplicate_observations() -> None:
    row = observation()
    request = {
        "fetches": [
            {
                "source_key": "cpi",
                "dataset": "CPI",
                "status": "LIVE",
                "last_successful_fetch": datetime(2026, 2, 1, tzinfo=timezone.utc),
                "observation_count": 1,
            }
        ],
        "observations": [row, row],
    }
    with pytest.raises(ValidationError, match="Duplicate observations"):
        IngestRequest.model_validate(request)


def test_ingestion_requires_fetch_metadata_for_each_source() -> None:
    request = {
        "fetches": [
            {
                "source_key": "cpi",
                "dataset": "CPI",
                "status": "LIVE",
                "last_successful_fetch": datetime(2026, 2, 1, tzinfo=timezone.utc),
                "observation_count": 1,
            }
        ],
        "observations": [observation(source_key="wpi")],
    }
    with pytest.raises(ValidationError, match="Missing fetch metadata"):
        IngestRequest.model_validate(request)


def test_ingestion_records_failed_sources_without_fabricated_observations() -> None:
    request = {
        "fetches": [
            {
                "source_key": "cpi",
                "dataset": "CPI",
                "status": "LIVE",
                "last_successful_fetch": datetime(2026, 2, 1, tzinfo=timezone.utc),
                "observation_count": 1,
            }
        ],
        "failed_sources": [{"source_key": "wpi", "dataset": "WPI", "error": "Source unavailable"}],
        "observations": [observation()],
    }
    parsed = IngestRequest.model_validate(request)
    assert [failure.source_key for failure in parsed.failed_sources] == ["wpi"]

    with pytest.raises(ValidationError, match="exactly one success or failure"):
        IngestRequest.model_validate(
            {
                **request,
                "failed_sources": [
                    {"source_key": "cpi", "dataset": "CPI", "error": "Conflicting source result"}
                ],
            }
        )


def test_health_endpoint_reports_optional_database_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["databaseConfigured"] is False


def test_ingestion_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "test-token")
    response = TestClient(app).post("/v1/ingest", json={})
    assert response.status_code == 401


def test_ingestion_reports_unconfigured_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "test-token")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    request = {
        "fetches": [
            {
                "source_key": "cpi",
                "dataset": "CPI",
                "status": "LIVE",
                "last_successful_fetch": datetime(2026, 2, 1, tzinfo=timezone.utc),
                "observation_count": 1,
            }
        ],
        "observations": [observation()],
    }
    response = TestClient(app).post(
        "/v1/ingest",
        headers={"Authorization": "Bearer test-token"},
        json=jsonable_encoder(IngestRequest.model_validate(request)),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "DATABASE_URL is not configured."
