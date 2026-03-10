# CLAUDE.md — Enterprise Knowledge Assistant

Full context for continuing this build in a new session.

---

## Build Status

**Phase: scaffolded, not yet installed or tested.**

All source files are written. No `uv sync` has been run, no `.env` exists yet,
and no documents have been ingested. The project is ready for the setup and
test phase.

---

## Stack Decisions

| Concern | Choice | Why this, not something else |
|---|---|---|
| Language | Python 3.11 | Needed for `X \| Y` union type syntax; older Python versions don't support it and the MCP SDK requires it |
| Package manager | uv | 10–100× faster than pip, built-in lockfile, and replaces pip + venv in one tool — no reason to use pip anymore |
| MCP framework | `mcp[cli]` ≥ 1.2 — FastMCP | Decorator-based tool definitions in ~5 lines vs writing a full JSON-RPC server by hand |
| Embeddings | Voyage AI `voyage-3` | Anthropic has **no** embeddings API at all — Voyage AI is their official recommended partner, not a workaround |
| LLM | Anthropic `claude-opus-4-6` | Most capable Claude model; used over Sonnet/Haiku because answer quality on enterprise docs matters more than cost here |
| Vector DB | ChromaDB (local, persistent) | Runs entirely on disk with no external service, unlike Pinecone or Weaviate which require accounts and internet access |
| PDF extraction | pypdf | Pure Python, processes files in-memory without executing embedded JavaScript, unlike pdfminer which is slower and less maintained |
| Config | python-dotenv + `.env` | Industry standard for keeping secrets out of source code; simpler than a full config library like Dynaconf for this scope |

**Important:** `embedding_function=None` is passed to `get_or_create_collection()` —
ChromaDB must not attempt its own embedding because we supply vectors directly from Voyage AI.

---

## Project Structure

```
enterprise-knowledge-assistant/
├── CLAUDE.md                               ← you are here
├── README.md                               — user-facing setup + claude_desktop_config.json
├── SECURITY.md                             — every security decision documented
├── .env.example                            — copy to .env, fill in keys
├── .gitignore                              — excludes .env, chroma_db/, logs/*.log
├── pyproject.toml                          — dependencies, Python ≥3.11, uv dev deps
│
├── docs/
│   └── architecture.md                    — ASCII diagram + component descriptions
│
├── src/
│   ├── audit/
│   │   └── logger.py                      — append-only JSON audit log (mode='a')
│   ├── ingestion/
│   │   ├── chunker.py                     — 800-char / 100-char-overlap chunks
│   │   ├── embedder.py                    — Voyage AI client, embed_texts / embed_query
│   │   └── pipeline.py                    — ChromaDB upsert, ingest_file / ingest_directory
│   └── query/
│       └── engine.py                      — RAG loop: embed → retrieve → Claude → answer
│
├── mcp-servers/
│   └── knowledge-server/
│       └── server.py                      — FastMCP, read_document + query tools
│
├── scripts/
│   └── ingest.py                          — CLI: uv run python scripts/ingest.py
│
└── logs/
    └── .gitkeep                           — audit.log written here at runtime
```

**Runtime-generated (not in git):**
- `chroma_db/` — ChromaDB vector store
- `logs/audit.log` — append-only audit log
- `.env` — secrets

---

## Environment Variables

All required. Defined in `.env` (copy from `.env.example`).

| Variable | Description | Why not hardcoded |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Console key — used by query engine for Claude | Hardcoding leaks the key into git history permanently |
| `VOYAGE_API_KEY` | Voyage AI key — used by embedder for document + query vectors | Same — API keys in source code get scraped and abused |
| `DOCS_DIR` | **Absolute path** to the documents directory | Different users/machines have different paths; env var makes it portable |
| `CHROMA_DB_PATH` | Path for ChromaDB storage (default: `./chroma_db`) | Lets you point to a different disk or shared drive without changing code |
| `LOG_PATH` | Path for audit log (default: `./logs/audit.log`) | Lets ops redirect logs to a centrally monitored location |
| `CLAUDE_MODEL` | Claude model ID (default: `claude-opus-4-6`) | Lets you swap to a cheaper model for testing without touching source code |

---

## Key Implementation Details

### Path traversal prevention (`server.py: _safe_resolve`)
```python
resolved = (DOCS_DIR / requested_path).resolve()   # eliminates ../
if not resolved.is_relative_to(DOCS_DIR):           # catches symlink escapes
    raise ValueError("Path traversal attempt blocked")
```
Two steps instead of one: `resolve()` alone doesn't prevent traversal, and `is_relative_to()` alone doesn't follow symlinks — you need both to be safe.

### ChromaDB collection
```python
client.get_or_create_collection(
    name="knowledge_base",
    embedding_function=None,       # we supply embeddings externally
    metadata={"hnsw:space": "cosine"},
)
```
`embedding_function=None` is set explicitly because without it ChromaDB defaults to its own model and would silently re-embed text, mixing two different vector spaces and breaking search.

### Chunk IDs (deterministic, enables safe re-ingestion)
```python
ids = [f"{file_path.stem}__{chunk['chunk_index']}" for chunk in chunks]
collection.upsert(ids=ids, embeddings=..., documents=..., metadatas=...)
```
Deterministic IDs + `upsert` instead of `add` means re-running ingestion updates existing chunks rather than creating duplicates.

### Streaming Claude call (avoids timeout on large context)
```python
with client.messages.stream(model=model, max_tokens=1024, ...) as stream:
    response = stream.get_final_message()
```
Streaming is used instead of a plain `.create()` call because large context windows can exceed HTTP timeout limits — streaming keeps the connection alive.

### Audit log (append-only)
```python
handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
logger.propagate = False   # never leaks to stdout
```
`mode='a'` instead of `'w'` so entries are never overwritten; `propagate=False` so audit entries don't accidentally appear in terminal output or other log handlers.

### Asymmetric embeddings (query vs document)
```python
embed_texts(texts, input_type="document")   # ingestion
embed_query(question, input_type="query")   # search
```
Voyage AI uses different vector spaces for documents and queries — using `"document"` for both would silently reduce retrieval accuracy.

---

## Setup Commands (first time)

```bash
# 1. Install dependencies
uv sync

# 2. Configure secrets
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY, VOYAGE_API_KEY, DOCS_DIR

# 3. Add documents to DOCS_DIR (or use docs/ folder)
# Supported: .txt .md .pdf

# 4. Ingest documents
uv run python scripts/ingest.py

# 5. Start MCP server
uv run python mcp-servers/knowledge-server/server.py
```

---

## Claude Desktop Config

File location:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "knowledge-assistant": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/enterprise-knowledge-assistant",
        "python",
        "mcp-servers/knowledge-server/server.py"
      ],
      "env": {
        "ANTHROPIC_API_KEY": "your_key",
        "VOYAGE_API_KEY": "your_key",
        "DOCS_DIR": "/absolute/path/to/docs",
        "CHROMA_DB_PATH": "/absolute/path/to/enterprise-knowledge-assistant/chroma_db",
        "LOG_PATH": "/absolute/path/to/enterprise-knowledge-assistant/logs/audit.log"
      }
    }
  }
}
```

---

## Next Steps

### Immediate (required to run)
- [ ] Run `uv sync` — installs all dependencies from pyproject.toml into a local venv
- [ ] Create `.env` from `.env.example` — without this, every module will raise `EnvironmentError` on startup
- [ ] Set `DOCS_DIR` to an absolute path — relative paths break when the server is launched from a different working directory
- [ ] Run `uv run python scripts/ingest.py` — ChromaDB is empty until this runs; queries will return nothing
- [ ] Test the MCP server: `uv run python mcp-servers/knowledge-server/server.py` — confirms imports and env vars work before connecting Claude Desktop
- [ ] Connect Claude Desktop using the config block above — use absolute paths in all fields to avoid launch failures

### Testing
- [ ] Write `tests/test_chunker.py` — chunking is stateless and easy to unit test without API calls
- [ ] Write `tests/test_path_safety.py` — the most critical security test; must reject `../`, absolute paths, and symlinks
- [ ] Write `tests/test_audit_logger.py` — verify `mode='a'` and `propagate=False` actually hold at runtime
- [ ] Write `tests/test_pipeline.py` — mock Voyage AI + ChromaDB to test upsert logic without network calls
- [ ] Write `tests/test_query_engine.py` — mock ChromaDB + Anthropic to verify the grounding prompt is built correctly

### Hardening
- [ ] Add `chattr +a logs/audit.log` to deployment docs — OS-level append-only flag that even root can't bypass without removing it first
- [ ] Add rate limiting on the MCP server — prevents a misbehaving client from running hundreds of expensive Claude queries in a loop
- [ ] Add max file size check in `read_document` — without it, a 500 MB PDF would be loaded entirely into memory
- [ ] Add document count / total size limits to `ingest_directory` — prevents accidental ingestion of an entire filesystem

### Features
- [ ] Add a `list_documents` MCP tool — lets Claude see what's available before choosing what to read
- [ ] Add a `re_ingest` MCP tool — allows updating a single document without re-running the full pipeline
- [ ] Support `.docx` via `python-docx` — Word docs are the most common enterprise format not yet supported
- [ ] Add metadata filtering in queries — lets users restrict search to a subfolder (e.g. "only search HR docs")
- [ ] Add a web UI (FastAPI + simple HTML) — makes the assistant accessible without Claude Desktop
- [ ] Add batch ingestion progress bar (tqdm) — large document sets take minutes with no feedback

### Observability
- [ ] Add structured metrics (ingest duration, query latency, chunk count) — needed to spot performance regressions
- [ ] Add a `scripts/audit_report.py` CLI — makes the append-only log human-readable without external tools
- [ ] Add log rotation via `RotatingFileHandler` — audit.log will grow indefinitely without it
