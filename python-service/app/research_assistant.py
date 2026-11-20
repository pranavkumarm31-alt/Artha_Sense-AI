import re
import uuid
from datetime import datetime, timezone
from typing import Any, cast

from fastapi.encoders import jsonable_encoder

from . import database
from .llm_provider import generate_grounded_answer
from .retrieval_service import infer_indicator, retrieve_evidence


_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?")
_CITATION_PATTERN = re.compile(r"\[(S\d+)\]")


def _numeric_values(text: str) -> set[float]:
    values: set[float] = set()
    for token in _NUMBER_PATTERN.findall(text):
        try:
            values.add(float(token.replace(",", "").rstrip("%")))
        except ValueError:
            continue
    return values


def _validate_answer(
    answer: str,
    returned_citations: list[str],
    evidence: list[dict[str, Any]],
    aliases: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    cited_in_text = set(_CITATION_PATTERN.findall(answer))
    allowed_ids = set(aliases)
    if not cited_in_text.issubset(allowed_ids) or not set(returned_citations).issubset(allowed_ids):
        raise ValueError("The generated answer referenced evidence that was not retrieved.")
    if len(returned_citations) != len(set(returned_citations)):
        raise ValueError("The generated answer returned duplicate citations.")
    if cited_in_text != set(returned_citations):
        raise ValueError("The generated answer citations are incomplete.")
    if evidence:
        if not cited_in_text:
            raise ValueError("The generated answer did not cite any retrieved evidence.")
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
            if sentence.strip() and not _CITATION_PATTERN.search(sentence):
                raise ValueError("Each factual answer sentence must cite retrieved evidence.")
    elif answer.strip() != (
        "I could not find sufficient persisted or ingested evidence to answer this. "
        "Please ingest official source data or ask about available indicators."
    ):
        raise ValueError("The answer must state that evidence is unavailable.")

    if evidence:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
            sentence_citations = set(_CITATION_PATTERN.findall(sentence))
            evidence_numbers: set[float] = set()
            for citation in sentence_citations:
                item = aliases[citation]
                evidence_numbers.update(_numeric_values(str(item.get("content", ""))))
                evidence_numbers.update(_numeric_values(str(item.get("title", ""))))
            answer_text = _CITATION_PATTERN.sub("", sentence)
            for value in _numeric_values(answer_text):
                if not any(
                    abs(value - source_value) <= max(0.00005, abs(source_value) * 0.000001)
                    for source_value in evidence_numbers
                ):
                    raise ValueError(
                        "The generated answer contains a number not present in its cited evidence."
                    )

    return [aliases[citation] for citation in returned_citations]


async def answer_research_question(
    *,
    owner_id: uuid.UUID,
    question: str,
    conversation_id: uuid.UUID | None,
) -> dict[str, Any]:
    if conversation_id is not None and not database.conversation_belongs_to(conversation_id, owner_id):
        raise PermissionError("Conversation not found.")

    history = (
        database.get_research_conversation_history(conversation_id, owner_id)
        if conversation_id is not None
        else []
    )
    previous_questions = [item["content"] for item in history if item["role"] == "user"][-2:]
    retrieval_query = " ".join([*previous_questions, question])
    evidence = await retrieve_evidence(
        retrieval_query,
        indicator_code=infer_indicator(question),
        limit=8,
    )
    aliases: dict[str, dict[str, Any]] = {}
    llm_evidence: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for index, item in enumerate(evidence, start=1):
        citation_id = f"S{index}"
        raw_metadata = item.get("metadata")
        metadata: dict[str, Any] = (
            cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
        )
        public_item: dict[str, Any] = {
            **item,
            "metadata": {**metadata, "citation_id": citation_id},
        }
        aliases[citation_id] = public_item
        citations.append(public_item)
        llm_evidence.append({
            "id": citation_id,
            "kind": item["kind"],
            "title": item["title"],
            "content": item["content"],
            "source_name": item["source_name"],
            "source_url": item["source_url"],
            "observation_period": item.get("observation_period"),
            "publication_date": item.get("publication_date"),
        })

    result = await generate_grounded_answer(question, history, llm_evidence)
    answer_value = result.get("answer")
    citation_values = result.get("citation_ids")
    if not isinstance(answer_value, str) or not isinstance(citation_values, list):
        raise ValueError("The language model returned an invalid answer.")
    valid_citation_values: list[str] = []
    for citation in cast(list[object], citation_values):
        if not isinstance(citation, str):
            raise ValueError("The language model returned invalid citation identifiers.")
        valid_citation_values.append(citation)
    answer = answer_value.strip()
    if not answer:
        raise ValueError("The language model returned an empty answer.")
    citations = _validate_answer(answer, valid_citation_values, citations, aliases)
    active_id = database.persist_research_exchange(
        owner_id,
        conversation_id,
        question,
        answer,
        jsonable_encoder(citations),
    )
    return {
        "conversation_id": str(active_id),
        "answer": answer,
        "citations": citations,
        "generated_at": datetime.now(timezone.utc),
    }
