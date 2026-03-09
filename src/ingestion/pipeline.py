"""
Ingestion pipeline — orchestrates document chunking, embedding, and storage.

Workflow:
  1. Read DOCS_DIR (or a specific file) from disk.
  2. Extract text (chunker.extract_text).
  3. Split into overlapping chunks (chunker.chunk_text).
  4. Embed each chunk via Voyage AI (embedder.embed_texts).
  5. Upsert into ChromaDB with metadata (source file, chunk index).
  6. Write an audit log entry for every ingest attempt.

Upsert semantics: re-ingesting the same file updates existing chunks and
adds new ones, so the pipeline is safe to re-run without creating duplicates.
"""

import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv

from src.audit.logger import log_event
from src.ingestion.chunker import chunk_text, extract_text
from src.ingestion.embedder import embed_texts

load_dotenv()

COLLECTION_NAME = "knowledge_base"

# Supported file extensions for ingestion
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".md"}


def get_chroma_client() -> chromadb.PersistentClient:
    """Return a ChromaDB client backed by a local persistent directory."""
    db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    return chromadb.PersistentClient(path=db_path)


def get_collection(client: chromadb.PersistentClient) -> chromadb.Collection:
    """
    Return (or create) the knowledge base collection.

    embedding_function=None: we always supply our own embeddings via
    Voyage AI, so ChromaDB must not attempt to embed text itself.

    hnsw:space=cosine: cosine similarity is the standard metric for
    semantic search with normalised embedding vectors.
    """
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,  # embeddings supplied externally
        metadata={"hnsw:space": "cosine"},
    )


def ingest_file(file_path: Path) -> int:
    """
    Ingest a single document into the vector database.

    Args:
        file_path: Absolute or project-relative path to the document.

    Returns:
        Number of chunks stored.

    Raises:
        Re-raises any exception after writing a failure audit entry.
    """
    try:
        text = extract_text(file_path)
        chunks = chunk_text(text, source=file_path.name)

        if not chunks:
            log_event(
                event_type="ingest",
                input_data=str(file_path),
                output_data="0 chunks (empty document)",
                source_document=file_path.name,
                success=True,
            )
            return 0

        texts = [c["text"] for c in chunks]
        embeddings = embed_texts(texts)

        chroma = get_chroma_client()
        collection = get_collection(chroma)

        # Deterministic IDs: allow safe re-ingestion (upsert)
        ids = [f"{file_path.stem}__{c['chunk_index']}" for c in chunks]
        metadatas = [
            {"source": c["source"], "chunk_index": c["chunk_index"]}
            for c in chunks
        ]

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        log_event(
            event_type="ingest",
            input_data=str(file_path),
            output_data=f"{len(chunks)} chunks stored",
            source_document=file_path.name,
            success=True,
        )
        return len(chunks)

    except Exception as exc:
        log_event(
            event_type="ingest",
            input_data=str(file_path),
            output_data=None,
            source_document=file_path.name,
            success=False,
            error=str(exc),
        )
        raise


def ingest_directory(docs_dir: Path | None = None) -> dict:
    """
    Ingest all supported documents in a directory (recursive).

    Args:
        docs_dir: Directory to scan. Defaults to DOCS_DIR env var or ./docs.

    Returns:
        Summary dict with keys 'processed', 'chunks', 'errors'.
    """
    if docs_dir is None:
        docs_dir = Path(os.getenv("DOCS_DIR", "./docs"))

    if not docs_dir.exists():
        raise FileNotFoundError(f"DOCS_DIR does not exist: {docs_dir}")

    results: dict = {"processed": 0, "chunks": 0, "errors": []}

    for file_path in sorted(docs_dir.rglob("*")):
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if not file_path.is_file():
            continue

        try:
            n = ingest_file(file_path)
            results["processed"] += 1
            results["chunks"] += n
        except Exception as exc:
            results["errors"].append(
                {"file": str(file_path), "error": str(exc)}
            )

    return results
