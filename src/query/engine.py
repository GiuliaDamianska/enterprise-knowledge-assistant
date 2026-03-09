"""
Query engine — retrieves relevant chunks from ChromaDB and generates answers
using Claude via the Anthropic API.

Workflow:
  1. Embed the user's question with Voyage AI (query input_type).
  2. Retrieve the top-N most similar chunks from ChromaDB.
  3. Build a grounded prompt with the retrieved context.
  4. Call Claude (claude-opus-4-6 by default) to generate an answer.
  5. Return the answer with source attribution.
  6. Write an audit log entry for every query attempt.

Security decisions:
- ANTHROPIC_API_KEY loaded from environment only.
- Claude is instructed to answer *only* from the provided context, preventing
  hallucination and ensuring answers are traceable to source documents.
- Long answers are truncated in the audit log to limit log file growth, but
  the full answer is always returned to the caller.
"""

import os

import anthropic
from dotenv import load_dotenv

from src.audit.logger import log_event
from src.ingestion.embedder import embed_query
from src.ingestion.pipeline import get_chroma_client, get_collection

load_dotenv()

# Module-level client; None until first call to get_anthropic_client()
_anthropic_client: anthropic.Anthropic | None = None

# Number of chunks to retrieve per query. Higher values increase recall but
# also increase prompt size and cost. 5 is a good default for most use cases.
DEFAULT_N_RESULTS = 5

# Maximum characters of an answer to store in the audit log.
# Full answers can be thousands of characters; this keeps log files manageable.
AUDIT_OUTPUT_MAX_CHARS = 500


def get_anthropic_client() -> anthropic.Anthropic:
    """Return the Anthropic client, initialising it on first call."""
    global _anthropic_client
    if _anthropic_client is None:
        # Security: key must come from the environment, never from source code
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file or environment before running."
            )
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def query_knowledge_base(
    question: str,
    n_results: int = DEFAULT_N_RESULTS,
) -> dict:
    """
    Answer a natural language question from the knowledge base.

    Args:
        question:  The user's question.
        n_results: Number of document chunks to retrieve for context.

    Returns:
        Dict with keys:
          - 'answer':      Claude's answer string.
          - 'sources':     Deduplicated list of source file names.
          - 'chunks_used': Number of chunks included in the prompt.

    Raises:
        Re-raises any exception after writing a failure audit entry.
    """
    try:
        # Step 1: embed the question using the query-optimised input type
        query_embedding = embed_query(question)

        # Step 2: retrieve semantically similar chunks from ChromaDB
        chroma = get_chroma_client()
        collection = get_collection(chroma)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        documents: list[str] = results["documents"][0]
        metadatas: list[dict] = results["metadatas"][0]

        if not documents:
            answer = (
                "No relevant documents found in the knowledge base. "
                "Please ingest some documents first."
            )
            sources: list[str] = []
        else:
            # Step 3: build a grounded context block for Claude
            context_parts = []
            for doc, meta in zip(documents, metadatas):
                context_parts.append(
                    f"[Source: {meta['source']}, chunk {meta['chunk_index']}]\n{doc}"
                )
            context = "\n\n---\n\n".join(context_parts)

            # Security / accuracy: Claude is explicitly instructed to answer
            # only from the provided context, not from its training data.
            # This ensures answers are traceable and prevents hallucination.
            system_prompt = (
                "You are an enterprise knowledge assistant. "
                "Answer questions using ONLY the context provided below. "
                "If the answer cannot be found in the context, say so clearly "
                "and do not speculate. Always cite the source document(s) you used."
            )

            user_prompt = (
                f"Context:\n{context}\n\n"
                f"Question: {question}"
            )

            # Step 4: call Claude for answer generation
            model = os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
            client = get_anthropic_client()

            # Use streaming-compatible call with get_final_message() for
            # resilience on long outputs (avoids HTTP timeout on large context)
            with client.messages.stream(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                response = stream.get_final_message()

            answer = response.content[0].text

            # Deduplicate source file names while preserving order
            seen: set[str] = set()
            sources = []
            for meta in metadatas:
                s = meta["source"]
                if s not in seen:
                    seen.add(s)
                    sources.append(s)

        # Step 5: write audit entry (truncate long answers to keep logs lean)
        log_event(
            event_type="query",
            input_data=question,
            output_data=answer[:AUDIT_OUTPUT_MAX_CHARS],
            source_document=", ".join(sources) if sources else None,
            success=True,
        )

        return {
            "answer": answer,
            "sources": sources,
            "chunks_used": len(documents),
        }

    except Exception as exc:
        log_event(
            event_type="query",
            input_data=question,
            output_data=None,
            source_document=None,
            success=False,
            error=str(exc),
        )
        raise
