"""
Embedder — generates vector embeddings via Voyage AI.

Why Voyage AI?
  Anthropic does not currently offer a standalone embeddings API endpoint.
  Voyage AI is Anthropic's recommended embeddings partner, purpose-built for
  retrieval-augmented generation workloads.
  See: https://docs.voyageai.com

Security decisions:
- API key loaded exclusively from the VOYAGE_API_KEY environment variable.
  It is never read from a config file, argument, or default value.
- The client is initialised lazily and cached at module level to avoid
  repeated env-var lookups and to allow tests to patch os.getenv.
"""

import os

import voyageai
from dotenv import load_dotenv

load_dotenv()

# Module-level client; None until first call to get_client()
_client: voyageai.Client | None = None

# Model choice: voyage-3 offers state-of-the-art retrieval quality.
# Switch to 'voyage-3-lite' for lower cost on high-volume workloads.
EMBEDDING_MODEL = "voyage-3"


def get_client() -> voyageai.Client:
    """Return the Voyage AI client, initialising it on first call."""
    global _client
    if _client is None:
        # Security: key must come from the environment, never from source code
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "VOYAGE_API_KEY is not set. "
                "Add it to your .env file or environment before running."
            )
        _client = voyageai.Client(api_key=api_key)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of document texts.

    Uses input_type='document' which is optimised for passages to be stored
    and searched, as opposed to short query strings.

    Args:
        texts: List of strings to embed (typically document chunks).

    Returns:
        List of float vectors, one per input text.
    """
    if not texts:
        return []
    client = get_client()
    result = client.embed(texts, model=EMBEDDING_MODEL, input_type="document")
    return result.embeddings


def embed_query(query: str) -> list[float]:
    """
    Embed a single natural-language query.

    Uses input_type='query' which is optimised for short search strings,
    improving retrieval accuracy when matched against 'document' embeddings.

    Args:
        query: The user's question.

    Returns:
        A single float vector.
    """
    client = get_client()
    result = client.embed([query], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]
