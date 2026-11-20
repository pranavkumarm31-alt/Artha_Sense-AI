import math
import os

import httpx


class EmbeddingProviderError(RuntimeError):
    pass


def _configuration() -> tuple[str, str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip()
    if not api_key or not base_url or not model:
        raise EmbeddingProviderError(
            "Semantic retrieval is unavailable. Configure OPENAI_API_KEY, "
            "OPENAI_BASE_URL and OPENAI_EMBEDDING_MODEL."
        )
    return api_key, base_url, model


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    api_key, base_url, model = _configuration()
    try:
        embeddings: list[list[float]] = []
        async with httpx.AsyncClient(timeout=45) as client:
            for offset in range(0, len(texts), 32):
                batch = texts[offset : offset + 32]
                response = await client.post(
                    f"{base_url}/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "input": batch},
                )
                response.raise_for_status()
                payload = response.json()
                data = sorted(payload["data"], key=lambda item: item["index"])
                vectors = [[float(value) for value in item["embedding"]] for item in data]
                if (
                    len(vectors) != len(batch)
                    or any(not vector or any(not math.isfinite(value) for value in vector)
                           for vector in vectors)
                ):
                    raise EmbeddingProviderError("Embedding provider returned an incomplete response.")
                embeddings.extend(vectors)
        if len(embeddings) != len(texts):
            raise EmbeddingProviderError("Embedding provider returned an incomplete response.")
        return embeddings
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise EmbeddingProviderError("Embedding provider request failed.") from error
