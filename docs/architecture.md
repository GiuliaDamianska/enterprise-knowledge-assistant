# Architecture

## Overview

The Enterprise Knowledge Assistant is a local RAG (Retrieval-Augmented Generation) system that lets you query your internal documents using natural language. It exposes its capabilities as MCP (Model Context Protocol) tools, making them available to Claude Desktop and any other MCP-compatible client.

```
                         ┌─────────────────────────────┐
                         │        Claude Desktop        │
                         │   (or any MCP client)        │
                         └──────────────┬──────────────┘
                                        │ MCP (stdio)
                         ┌──────────────▼──────────────┐
                         │      knowledge-server        │
                         │   mcp-servers/knowledge-     │
                         │   server/server.py           │
                         │                              │
                         │  Tools:                      │
                         │  • read_document(path)       │
                         │  • query(question)           │
                         └──────┬─────────────┬────────┘
                                │             │
               ┌────────────────▼──┐   ┌──────▼──────────────┐
               │   Query Engine    │   │  Audit Logger        │
               │ src/query/        │   │ src/audit/logger.py  │
               │ engine.py         │   │                      │
               └────┬──────────┬──┘   │ logs/audit.log       │
                    │          │       │ (append-only JSON)   │
          ┌─────────▼──┐  ┌────▼────┐ └──────────────────────┘
          │  ChromaDB  │  │ Anthropic│
          │ (local)    │  │  API     │
          │            │  │ (Claude) │
          └─────────▲──┘  └─────────┘
                    │
          ┌─────────┴──────────────────┐
          │     Ingestion Pipeline     │
          │  scripts/ingest.py         │
          │  src/ingestion/            │
          │  ├── pipeline.py           │
          │  ├── chunker.py            │
          │  └── embedder.py           │
          └──────────────┬─────────────┘
                         │
               ┌──────────▼──────────┐
               │   Voyage AI API     │
               │   (embeddings)      │
               └─────────────────────┘
```

## Components

### MCP Server (`mcp-servers/knowledge-server/server.py`)

The MCP server is the entry point for all client interactions. It exposes two tools:

- **`read_document(path)`** — Reads a file from `DOCS_DIR`. Path traversal is prevented by resolving to an absolute path and verifying it remains inside `DOCS_DIR` via `is_relative_to()`. Only `.txt`, `.md`, and `.pdf` files are permitted.

- **`query(question)`** — Performs a semantic search over ingested documents and returns a grounded answer with source attribution.

### Ingestion Pipeline (`src/ingestion/`)

Before the knowledge base can be queried, documents must be ingested:

1. **Chunker** (`chunker.py`): Splits documents into 800-character overlapping windows (100-character overlap). Supports `.txt`, `.md`, and `.pdf` via pypdf.

2. **Embedder** (`embedder.py`): Generates vector embeddings using Voyage AI's `voyage-3` model. Documents use `input_type="document"`; queries use `input_type="query"` for asymmetric retrieval.

3. **Pipeline** (`pipeline.py`): Orchestrates chunking and embedding, then upserts chunks into ChromaDB with deterministic IDs to support safe re-ingestion.

### Query Engine (`src/query/engine.py`)

Handles the retrieval-augmented generation loop:

1. Embed the user's question with Voyage AI (`input_type="query"`).
2. Retrieve the top-5 most similar chunks from ChromaDB (cosine similarity).
3. Build a grounded prompt that includes retrieved context.
4. Call Claude (`claude-opus-4-6`) with an instruction to answer only from provided context.
5. Return the answer with deduplicated source attribution.

### Audit Logger (`src/audit/logger.py`)

Every document read, query, and ingestion attempt is logged as a JSON line to `logs/audit.log`. The file is opened in append mode (`'a'`) and log propagation is disabled to ensure entries are never overwritten or silently dropped.

Log entry structure:
```json
{
  "timestamp": "2025-01-15T10:30:00+00:00",
  "event_type": "query",
  "input": "What is our vacation policy?",
  "output": "According to the HR handbook...",
  "source_document": "hr-handbook.pdf",
  "success": true,
  "error": null
}
```

## Data Flow

### Ingestion (one-time setup)

```
docs/ → chunker → voyage AI → ChromaDB (chroma_db/)
                                    ↓
                              audit.log entry
```

### Query (runtime)

```
question → voyage AI (query embed) → ChromaDB (top-5 chunks)
                                           ↓
                              Claude API (grounded prompt)
                                           ↓
                         answer + sources → MCP client
                                           ↓
                                     audit.log entry
```

## Security Model

| Threat | Control |
|--------|---------|
| Path traversal | `Path.resolve()` + `is_relative_to()` in `_safe_resolve()` |
| Credential exposure | All secrets in `.env`, never committed (`.gitignore`) |
| Arbitrary file reads | Extension whitelist (`.txt`, `.md`, `.pdf` only) |
| Log tampering | Append-only file handle; no delete/overwrite in code |
| Prompt injection | Claude instructed to answer only from provided context |
| Dependency confusion | Pinned versions in `pyproject.toml` |

## Embedding Model Note

Anthropic does not currently offer a standalone embeddings API endpoint. Voyage AI (`voyageai` package) is Anthropic's recommended embeddings provider and is used here for document and query embeddings. The Anthropic API is used exclusively for answer generation via Claude.
