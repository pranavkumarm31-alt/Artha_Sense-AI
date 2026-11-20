import asyncio
import io

import pytest
from fastapi.testclient import TestClient

from app.document_ingestion import (
    chunk_text,
    document_sha256,
    extract_document_text,
    validate_official_source_url,
)
from app.embedding_service import EmbeddingProviderError, embed_texts
from app.llm_provider import LLMProviderError, generate_grounded_answer
from app.main import app
from app.research_assistant import _validate_answer
from app.retrieval_service import retrieve_evidence


def test_text_ingestion_chunks_and_hashes_deterministically():
    text, content_type = extract_document_text(
        "report.txt", "text/plain", b"Official economic report\nGDP growth was 6.5 percent."
    )
    chunks = chunk_text(text)

    assert content_type == "text/plain"
    assert chunks == ["Official economic report GDP growth was 6.5 percent."]
    assert document_sha256(b"same") == document_sha256(b"same")
    assert document_sha256(b"same") != document_sha256(b"different")


def _pdf_with_text(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n".encode())
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(document)


def test_pdf_extraction_reads_source_text():
    text, content_type = extract_document_text(
        "official-report.pdf", "application/pdf", _pdf_with_text("GDP growth report")
    )

    assert content_type == "application/pdf"
    assert "GDP growth report" in text


def test_chunking_overlaps_large_sections():
    chunks = chunk_text("word " * 700)

    assert len(chunks) > 1
    assert all(len(chunk) <= 1200 for chunk in chunks)
    assert chunks[0][-40:] in chunks[1]


@pytest.mark.parametrize(
    "url",
    [
        "https://mospi.gov.in/reports/economic.pdf",
        "https://www.rbi.org.in/Scripts/PublicationReportDetails.aspx",
    ],
)
def test_official_https_sources_are_accepted(url):
    validate_official_source_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://mospi.gov.in/report.pdf",
        "https://example.com/report.pdf",
        "https://mospi.gov.in.evil.example/report.pdf",
        "https://user:pass@mospi.gov.in/report.pdf",
        "https://mospi.gov.in:8443/report.pdf",
    ],
)
def test_untrusted_or_insecure_source_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_official_source_url(url)


def test_document_extraction_rejects_bad_types_and_oversized_payloads():
    with pytest.raises(ValueError, match="Only PDF"):
        extract_document_text("report.docx", "application/octet-stream", b"data")
    with pytest.raises(ValueError, match="10 MB"):
        extract_document_text("report.txt", "text/plain", b"x" * (10 * 1024 * 1024 + 1))


def test_retrieval_combines_structured_data_and_semantic_chunks(monkeypatch):
    monkeypatch.setattr(
        "app.retrieval_service.database.get_structured_research_evidence",
        lambda **_kwargs: [{
            "id": "obs:cpi_inflation:2026-10",
            "kind": "observation",
            "title": "CPI inflation — 2026-10",
            "content": "Observed value: 4.2 percent.",
            "source_name": "MoSPI",
            "source_url": "https://mospi.gov.in",
            "observation_period": "2026-10",
            "publication_date": None,
            "metadata": {"indicator_code": "cpi_inflation"},
        }],
    )
    monkeypatch.setattr(
        "app.retrieval_service.database.search_research_chunks",
        lambda **_kwargs: [{
            "document_id": "doc-id",
            "title": "Inflation Report",
            "source_name": "RBI",
            "source_url": "https://rbi.org.in/report",
            "publication_date": None,
            "version": "2026-01",
            "chunk_index": 0,
            "content": "Consumer inflation overview for October.",
            "embedding": [1.0, 0.0],
            "metadata": {},
        }],
    )
    monkeypatch.setattr("app.retrieval_service.database.get_history_range", lambda *_args, **_kwargs: [])
    async def fake_embeddings(_texts):
        return [[1.0, 0.0]]

    monkeypatch.setattr("app.retrieval_service.embed_texts", fake_embeddings)

    result = asyncio.run(retrieve_evidence("latest CPI inflation", limit=4))

    assert {item["kind"] for item in result} == {"observation", "document"}


def test_grounding_rejects_uncited_numbers_and_unknown_citations():
    evidence = [{
        "id": "S1",
        "title": "GDP 2025-26",
        "content": "Observed GDP growth: 6.5 percent in 2025-26.",
    }]
    aliases = {
        "S1": {
            **evidence[0],
            "id": "obs:gdp:2025-26",
            "metadata": {"citation_id": "S1"},
        }
    }

    with pytest.raises(ValueError, match="number not present"):
        _validate_answer("GDP growth was 7.2% [S1].", ["S1"], evidence, aliases)
    with pytest.raises(ValueError, match="referenced evidence"):
        _validate_answer("GDP growth was 6.5% [S2].", ["S2"], evidence, aliases)


def test_grounding_accepts_cited_source_values():
    evidence = [{
        "id": "S1",
        "title": "GDP 2025-26",
        "content": "Observed GDP growth: 6.5 percent in 2025-26.",
    }]
    aliases = {
        "S1": {
            **evidence[0],
            "id": "obs:gdp:2025-26",
            "metadata": {"citation_id": "S1"},
        }
    }

    citations = _validate_answer("GDP growth was 6.5% [S1].", ["S1"], evidence, aliases)

    assert len(citations) == 1


def test_grounding_requires_sentence_citations_and_rejects_unsupported_values():
    evidence = [{
        "id": "S1",
        "title": "CPI 2026-10",
        "content": "Observed CPI inflation: 4.2 percent.",
    }]
    aliases = {
        "S1": {
            **evidence[0],
            "id": "obs:cpi:2026-10",
            "metadata": {"citation_id": "S1"},
        }
    }

    with pytest.raises(ValueError, match="Each factual answer sentence"):
        _validate_answer(
            "CPI inflation is 4.2% [S1]. WPI is stable.",
            ["S1"],
            evidence,
            aliases,
        )
    with pytest.raises(ValueError, match="cited evidence"):
        _validate_answer(
            "CPI inflation is 4.2% [S1] and GDP is 6.5% [S1].",
            ["S1"],
            evidence,
            aliases,
        )


def test_empty_evidence_requires_explicit_unavailable_response():
    expected = (
        "I could not find sufficient persisted or ingested evidence to answer this. "
        "Please ingest official source data or ask about available indicators."
    )
    assert _validate_answer(expected, [], [], {}) == []
    with pytest.raises(ValueError, match="evidence is unavailable"):
        _validate_answer("The GDP growth is 6.5%.", [], [], {})


def test_api_requires_service_authentication_and_owner_scope(monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "test-token")
    client = TestClient(app)

    unauthorized = client.get("/v1/research/history")
    missing_owner = client.get(
        "/v1/research/history", headers={"Authorization": "Bearer test-token"}
    )

    assert unauthorized.status_code == 401
    assert missing_owner.status_code == 422


def test_document_ingestion_requires_separate_ingestion_secret(monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_API_TOKEN", "test-token")
    monkeypatch.setenv("RESEARCH_INGEST_TOKEN", "ingest-token")
    client = TestClient(app)
    response = client.post(
        "/v1/research/documents/ingest",
        headers={"Authorization": "Bearer test-token"},
        data={
            "title": "Official report",
            "source_name": "MoSPI",
            "source_url": "https://mospi.gov.in/report",
            "version": "2026-01",
        },
        files={"file": ("report.txt", io.BytesIO(b"report"), "text/plain")},
    )

    assert response.status_code == 401


def test_provider_configuration_errors_are_explicit(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EmbeddingProviderError, match="Configure OPENAI_API_KEY"):
        asyncio.run(embed_texts(["economic report"]))
    with pytest.raises(LLMProviderError, match="Configure OPENAI_API_KEY"):
        asyncio.run(generate_grounded_answer("question", [], []))


def test_embedding_provider_batches_large_document_inputs(monkeypatch):
    class FakeResponse:
        def __init__(self, batch):
            self.batch = batch

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": index, "embedding": [float(index + 1), 0.0]}
                    for index, _ in enumerate(self.batch)
                ]
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            self.batch_sizes = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, headers, json):
            assert headers["Authorization"] == "Bearer test-key"
            self.batch_sizes.append(len(json["input"]))
            return FakeResponse(json["input"])

    client = FakeClient()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "test-chat")
    monkeypatch.setattr("app.embedding_service.httpx.AsyncClient", lambda **kwargs: client)

    vectors = asyncio.run(embed_texts(["chunk"] * 33))

    assert len(vectors) == 33
    assert client.batch_sizes == [32, 1]
