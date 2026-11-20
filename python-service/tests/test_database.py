import os
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from app.database import (
    add_research_message,
    conversation_belongs_to,
    create_research_conversation,
    get_anomalies,
    get_anomaly_summary,
    get_history,
    ingest,
    migrate,
    get_research_conversations,
    persist_analysis,
    persist_anomalies,
    persist_research_exchange,
    persist_research_document,
)
from app.main import app
from app.schemas import IngestRequest


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests.",
)


def source_fetch(source_key: str, dataset: str) -> dict[str, object]:
    return {
        "source_key": source_key,
        "dataset": dataset,
        "status": "LIVE",
        "last_successful_fetch": datetime(2026, 11, 20, 16, 35, tzinfo=timezone.utc),
        "observation_count": 1,
    }


def observation(
    *,
    source_key: str,
    metric_code: str,
    name: str,
    observation_period: str,
    observation_start: date,
    fiscal_year: str,
    value: float,
    unit: str,
    base_year: str,
    frequency: str = "monthly",
    month: int | None = None,
    quarter: str | None = None,
) -> dict[str, object]:
    return {
        "source_key": source_key,
        "metric_code": metric_code,
        "name": name,
        "frequency": frequency,
        "observation_period": observation_period,
        "observation_start": observation_start,
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "month": month,
        "value": value,
        "value_type": "official",
        "unit": unit,
        "base_year": base_year,
        "source_status": "LIVE",
        "last_fetched_at": datetime(2026, 11, 20, 16, 35, tzinfo=timezone.utc),
        "publication_date": None,
        "source_metadata": {"verifiedFrom": "existing MoSPI dashboard API response"},
    }


@pytest.fixture(autouse=True)
def test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    if TEST_DATABASE_URL:
        monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)


def official_payload() -> IngestRequest:
    observations = [
        observation(
            source_key="nas",
            metric_code="gdp_real_growth",
            name="Real GDP growth",
            observation_period="Q2 FY 2025-26",
            observation_start=date(2025, 7, 1),
            fiscal_year="2025-26",
            value=8.2,
            unit="%",
            base_year="2011-12",
            frequency="quarterly",
            quarter="Q2",
        ),
        observation(
            source_key="cpi",
            metric_code="cpi_inflation",
            name="CPI inflation",
            observation_period="Oct 2026",
            observation_start=date(2026, 10, 1),
            fiscal_year="2026-27",
            value=6.09,
            unit="%",
            base_year="2024",
            month=10,
        ),
        observation(
            source_key="wpi",
            metric_code="wpi_inflation",
            name="WPI inflation",
            observation_period="Oct 2026",
            observation_start=date(2026, 10, 1),
            fiscal_year="2026-27",
            value=12.29,
            unit="%",
            base_year="2022-23",
            month=10,
        ),
        observation(
            source_key="iip",
            metric_code="iip_growth",
            name="IIP growth",
            observation_period="Mar 2026",
            observation_start=date(2026, 3, 1),
            fiscal_year="2025-26",
            value=4.1,
            unit="%",
            base_year="2011-12",
            month=3,
        ),
    ]
    return IngestRequest.model_validate(
        {
            "source_name": "Ministry of Statistics and Programme Implementation (MoSPI)",
            "source_url": "https://mcp.mospi.gov.in/",
            "fetches": [
                source_fetch("nas", "NAS"),
                source_fetch("cpi", "CPI"),
                source_fetch("wpi", "WPI"),
                source_fetch("iip", "IIP"),
            ],
            "observations": observations,
        }
    )


def test_migration_is_idempotent() -> None:
    first = migrate()
    second = migrate()
    assert set(second).isdisjoint(first)
    assert second == []


def test_ingest_duplicate_and_history_preserve_source_provenance() -> None:
    migrate()
    payload = official_payload()

    first_count = ingest(payload)
    second_count = ingest(payload)

    assert first_count == 4
    assert second_count == 4
    history = get_history("gdp_real_growth")
    assert len(history) == 1
    assert history[0].value == 8.2
    assert history[0].source_key == "nas"
    assert history[0].source_name == "Ministry of Statistics and Programme Implementation (MoSPI)"
    assert history[0].source_url == "https://mcp.mospi.gov.in/"
    assert history[0].source_status == "LIVE"


def test_failed_source_does_not_overwrite_valid_observation() -> None:
    migrate()
    payload = official_payload()
    ingest(payload)

    failed_payload = IngestRequest.model_validate(
        {
            "source_name": "Ministry of Statistics and Programme Implementation (MoSPI)",
            "source_url": "https://mcp.mospi.gov.in/",
            "fetches": [
                {
                    "source_key": "nas",
                    "dataset": "NAS",
                    "status": "LIVE",
                    "last_successful_fetch": datetime(
                        2026, 11, 20, 17, 35, tzinfo=timezone.utc
                    ),
                    "observation_count": 1,
                }
            ],
            "failed_sources": [
                {
                    "source_key": "wpi",
                    "dataset": "WPI",
                    "error": "MoSPI timeout",
                }
            ],
            "observations": [
                observation(
                    source_key="nas",
                    metric_code="gdp_real_growth",
                    name="Real GDP growth",
                    observation_period="Q2 FY 2025-26",
                    observation_start=date(2025, 7, 1),
                    fiscal_year="2025-26",
                    value=8.2,
                    unit="%",
                    base_year="2011-12",
                    frequency="quarterly",
                    quarter="Q2",
                )
            ],
        }
    )
    ingest(failed_payload)

    history = get_history("gdp_real_growth")
    assert len(history) == 1
    assert history[0].value == 8.2


def test_fastapi_ingestion_and_history_require_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "arthasense-test-token")
    migrate()
    payload = official_payload()
    client = TestClient(app)

    unauthorized = client.post("/v1/ingest", json=jsonable_encoder(payload))
    assert unauthorized.status_code == 401

    headers = {"Authorization": "Bearer arthasense-test-token"}
    ingested = client.post(
        "/v1/ingest",
        headers=headers,
        json=jsonable_encoder(payload),
    )
    assert ingested.status_code == 200
    assert ingested.json()["observations_received"] == 4

    retrieved = client.get(
        "/v1/history/gdp_real_growth",
        headers=headers,
        params={"limit": 10},
    )
    assert retrieved.status_code == 200
    rows = retrieved.json()
    assert len(rows) == 1
    assert rows[0]["source_key"] == "nas"
    assert rows[0]["source_name"] == "Ministry of Statistics and Programme Implementation (MoSPI)"
    assert rows[0]["source_status"] == "LIVE"


def test_fastapi_insufficient_forecast_is_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "arthasense-test-token")
    migrate()
    payload = official_payload()
    ingest(payload)
    client = TestClient(app)
    headers = {"Authorization": "Bearer arthasense-test-token"}

    response = client.post(
        "/v1/forecasts/generate",
        headers=headers,
        json={
            "indicator_code": "gdp_real_growth",
            "model": "naive",
            "horizon": 1,
            "persist": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["forecasts"] == []
    assert body["metrics"] is None
    assert "at least 12" in body["warning"]


def test_analysis_persistence_is_idempotent() -> None:
    migrate()
    inserted = persist_analysis(
        analysis_type="trend",
        observation_period="Oct 2026",
        content={"indicator_code": "wpi_inflation", "trend": "upward"},
        source_observations=[
            {
                "metric_code": "wpi_inflation",
                "observation_period": "Oct 2026",
                "value": 12.29,
            }
        ],
        analysis_version="1.0",
    )
    repeated = persist_analysis(
        analysis_type="trend",
        observation_period="Oct 2026",
        content={"indicator_code": "wpi_inflation", "trend": "upward"},
        source_observations=[
            {
                "metric_code": "wpi_inflation",
                "observation_period": "Oct 2026",
                "value": 12.29,
            }
        ],
        analysis_version="1.0",
    )
    assert inserted == 1
    assert repeated == 0


def test_anomaly_persistence_is_idempotent_and_filterable() -> None:
    migrate()
    payload = official_payload()
    ingest(payload)
    anomaly = SimpleNamespace(
        observation_start=date(2026, 10, 1),
        observation_period="Oct 2026",
        actual_value=6.09,
        expected_value=5.0,
        absolute_deviation=1.09,
        percentage_deviation=21.8,
        anomaly_score=2.8,
        severity="medium",
        detection_method="zscore",
        explanation="Test fixture anomaly for database verification.",
        detected_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
        model_version="zscore-historical-1.0",
        source_key="cpi",
        source_name="Ministry of Statistics and Programme Implementation (MoSPI)",
        source_url="https://mcp.mospi.gov.in/",
    )
    first = persist_anomalies(
        [anomaly],
        indicator_code="cpi_inflation",
        model_parameters={"threshold": 2.5},
    )
    repeated = persist_anomalies(
        [anomaly],
        indicator_code="cpi_inflation",
        model_parameters={"threshold": 2.5},
    )
    assert first == 1
    assert repeated == 1
    rows = get_anomalies(
        indicator_code="cpi_inflation",
        severity="medium",
        method="zscore",
        limit=10,
    )
    assert len(rows) == 1
    summary = get_anomaly_summary()
    assert summary["total"] >= 1


def test_anomaly_fastapi_authentication_and_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "arthasense-test-token")
    client = TestClient(app)
    unauthorized = client.get("/v1/anomalies/methods")
    assert unauthorized.status_code == 401
    headers = {"Authorization": "Bearer arthasense-test-token"}
    methods = client.get("/v1/anomalies/methods", headers=headers)
    assert methods.status_code == 200
    assert "isolation_forest" in {
        item["code"] for item in methods.json()["methods"]
    }


def test_research_documents_are_versioned_and_idempotent() -> None:
    migrate()
    import uuid

    checksum = "a" * 64
    first_id = uuid.uuid4()
    first, inserted = persist_research_document(
        document_id=first_id,
        title="Official report",
        source_name="MoSPI",
        source_url="https://mospi.gov.in/report",
        publication_date=date(2026, 10, 1),
        version="2026-10",
        content_sha256=checksum,
        content_type="text/plain",
        metadata={},
        chunks=["GDP report text"],
        embeddings=[[0.1, 0.2]],
    )
    duplicate, duplicate_inserted = persist_research_document(
        document_id=uuid.uuid4(),
        title="Changed title must not overwrite",
        source_name="MoSPI",
        source_url="https://mospi.gov.in/report",
        publication_date=date(2026, 10, 1),
        version="2026-10",
        content_sha256=checksum,
        content_type="text/plain",
        metadata={},
        chunks=["replacement"],
        embeddings=[[0.3, 0.4]],
    )

    assert inserted is True
    assert duplicate_inserted is False
    assert str(first["id"]) == str(duplicate["id"])
    assert duplicate["title"] == "Official report"

    version_two, version_two_inserted = persist_research_document(
        document_id=uuid.uuid4(),
        title="Official report",
        source_name="MoSPI",
        source_url="https://mospi.gov.in/report",
        publication_date=date(2026, 10, 1),
        version="2026-11",
        content_sha256="b" * 64,
        content_type="text/plain",
        metadata={},
        chunks=["revised GDP report text"],
        embeddings=[[0.2, 0.3]],
    )
    assert version_two_inserted is True
    assert version_two["version"] == "2026-11"


def test_research_conversations_are_isolated_by_owner() -> None:
    migrate()
    import uuid

    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    conversation = create_research_conversation(owner_a, "GDP question")
    conversation_id = uuid.UUID(str(conversation["id"]))
    add_research_message(conversation_id, "user", "What is GDP growth?")
    add_research_message(conversation_id, "assistant", "See evidence.", [])

    owner_a_history = get_research_conversations(owner_a)
    owner_b_history = get_research_conversations(owner_b)

    assert len(owner_a_history) == 1
    assert len(owner_a_history[0]["messages"]) == 2
    assert owner_b_history == []
    assert conversation_belongs_to(conversation_id, owner_a)
    assert not conversation_belongs_to(conversation_id, owner_b)

    exchange_id = persist_research_exchange(
        owner_a,
        None,
        "What is the latest CPI?",
        "See the cited observation.",
        [{"id": "obs:cpi:Oct 2026", "publication_date": "2026-10-01"}],
    )
    updated_history = get_research_conversations(owner_a)
    exchange_history = next(
        item for item in updated_history if str(item["id"]) == str(exchange_id)
    )
    assert exchange_history["messages"][1]["citations"][0]["publication_date"] == "2026-10-01"


def test_research_chat_api_persists_grounded_exchange_and_enforces_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    async def evidence(_query: str, **_kwargs: object) -> list[dict[str, object]]:
        return [{
            "id": "obs:gdp_real_growth:Q2 FY 2025-26",
            "kind": "observation",
            "title": "GDP growth — Q2 FY 2025-26",
            "content": "Observed value: 6.5 percent.",
            "source_name": "MoSPI",
            "source_url": "https://mcp.mospi.gov.in/",
            "observation_period": "Q2 FY 2025-26",
            "publication_date": date(2025, 11, 1),
            "metadata": {"indicator_code": "gdp_real_growth", "value": 6.5},
        }]

    async def answer(
        _question: str,
        _history: list[dict[str, str]],
        _evidence: list[dict[str, object]],
    ) -> dict[str, object]:
        return {"answer": "GDP growth was 6.5% [S1].", "citation_ids": ["S1"]}

    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "arthasense-test-token")
    monkeypatch.setattr("app.research_assistant.retrieve_evidence", evidence)
    monkeypatch.setattr("app.research_assistant.generate_grounded_answer", answer)
    migrate()
    client = TestClient(app)
    owner_a = str(uuid.uuid4())
    owner_b = str(uuid.uuid4())
    headers = {"Authorization": "Bearer arthasense-test-token", "X-Research-Owner": owner_a}

    chat_response = client.post(
        "/v1/research/chat",
        headers=headers,
        json={"question": "What is the latest GDP growth?"},
    )
    assert chat_response.status_code == 200
    body = chat_response.json()
    assert body["answer"] == "GDP growth was 6.5% [S1]."
    assert body["citations"][0]["source_name"] == "MoSPI"
    assert body["citations"][0]["publication_date"] == "2025-11-01"

    stolen_conversation = client.post(
        "/v1/research/chat",
        headers={**headers, "X-Research-Owner": owner_b},
        json={
            "question": "Continue this conversation.",
            "conversation_id": body["conversation_id"],
        },
    )
    history = client.get("/v1/research/history", headers=headers)

    assert stolen_conversation.status_code == 404
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert len(history.json()[0]["messages"]) == 2
