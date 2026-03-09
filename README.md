# Enterprise Knowledge Assistant

A local, production-quality RAG (Retrieval-Augmented Generation) system that lets you query your internal documents using natural language. Built with Python 3.11, the MCP Python SDK, ChromaDB, Voyage AI embeddings, and Claude.

## Features

- **MCP server** — exposes `read_document` and `query` tools to Claude Desktop (or any MCP client)
- **Document ingestion** — chunks `.txt`, `.md`, and `.pdf` files and stores embeddings in a local ChromaDB
- **Semantic search** — retrieves the most relevant chunks using Voyage AI vector embeddings
- **Grounded answers** — Claude answers only from retrieved context, with source attribution
- **Audit logging** — every read and query is logged to `logs/audit.log` (append-only JSON lines)
- **Security-first** — path traversal prevention, extension whitelist, no hardcoded credentials

> **Note on embeddings:** Anthropic does not currently offer a standalone embeddings API endpoint. This project uses [Voyage AI](https://voyageai.com) — Anthropic's recommended embeddings partner — for document and query embeddings. The Anthropic API is used for answer generation via Claude.

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- An [Anthropic API key](https://console.anthropic.com)
- A [Voyage AI API key](https://dash.voyageai.com)

---

## Quick Start

### 1. Clone and install

```bash
git clone <repo-url>
cd enterprise-knowledge-assistant
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your API keys and DOCS_DIR
```

### 3. Add documents

Put `.txt`, `.md`, or `.pdf` files in your `DOCS_DIR` (or the `docs/` folder):

```bash
cp your-documents/*.pdf docs/
```

### 4. Ingest documents

```bash
uv run python scripts/ingest.py
# Or ingest a specific directory:
uv run python scripts/ingest.py --dir /path/to/docs
# Or a single file:
uv run python scripts/ingest.py --file docs/handbook.pdf
```

### 5. Start the MCP server

```bash
uv run python mcp-servers/knowledge-server/server.py
```

---

## Claude Desktop Integration

Add the following to your `claude_desktop_config.json`:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

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
        "ANTHROPIC_API_KEY": "your_anthropic_api_key",
        "VOYAGE_API_KEY": "your_voyage_api_key",
        "DOCS_DIR": "/absolute/path/to/your/docs",
        "CHROMA_DB_PATH": "/absolute/path/to/enterprise-knowledge-assistant/chroma_db",
        "LOG_PATH": "/absolute/path/to/enterprise-knowledge-assistant/logs/audit.log"
      }
    }
  }
}
```

> **Security:** Prefer loading credentials from `.env` rather than embedding them directly in `claude_desktop_config.json`. The `env` block above is shown for completeness; if you have a `.env` file in the project root, omit those keys from `env` and the server will load them automatically.

After editing the config, restart Claude Desktop. You should see the `knowledge-assistant` server listed under **Settings → MCP Servers**.

---

## Project Structure

```
enterprise-knowledge-assistant/
├── README.md
├── SECURITY.md
├── .env.example            # Template — copy to .env and fill in secrets
├── .gitignore
├── pyproject.toml          # uv/pip dependencies, Python 3.11+
│
├── docs/
│   └── architecture.md     # System design and data flow
│
├── src/
│   ├── audit/
│   │   └── logger.py       # Append-only JSON audit logger
│   ├── ingestion/
│   │   ├── chunker.py      # Text + PDF chunking
│   │   ├── embedder.py     # Voyage AI embeddings
│   │   └── pipeline.py     # Ingest orchestration + ChromaDB upsert
│   └── query/
│       └── engine.py       # RAG query + Claude answer generation
│
├── mcp-servers/
│   └── knowledge-server/
│       └── server.py       # MCP server (FastMCP) with path safety
│
├── scripts/
│   └── ingest.py           # CLI ingestion script
│
├── logs/
│   └── .gitkeep            # audit.log written here at runtime
│
└── chroma_db/              # Created at runtime by ChromaDB
```

---

## Usage Examples

Once Claude Desktop is connected, you can ask:

- *"What does our employee handbook say about remote work?"*
- *"Summarise the key points of the Q4 financial report."*
- *"What are the security requirements in the IT policy?"*

Or use the tools directly:

- `read_document("policies/hr-handbook.pdf")` — returns the full text
- `query("What is the vacation accrual rate?")` — returns a grounded answer

---

## Re-ingesting Documents

The pipeline uses deterministic chunk IDs, so re-running ingestion safely updates existing chunks:

```bash
uv run python scripts/ingest.py
```

---

## Security

See [SECURITY.md](SECURITY.md) for a full description of the security decisions and threat mitigations in this project.

Key points:
- **Path traversal** is prevented by `Path.resolve()` + `is_relative_to()` in the MCP server.
- **Credentials** are loaded from environment variables only — never hardcoded.
- **Audit log** is opened in append mode; entries cannot be overwritten by the application.
- **File type whitelist** (`.txt`, `.md`, `.pdf`) prevents reads of sensitive files.

---

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Lint
uv run ruff check src/ mcp-servers/ scripts/
```

---

## Architecture

See [docs/architecture.md](docs/architecture.md) for a detailed description of the system components, data flow, and security model.
