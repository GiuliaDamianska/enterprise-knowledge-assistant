"""
MCP Knowledge Server — exposes document reading and semantic querying as
MCP tools for use with Claude Desktop and other MCP clients.

Tools exposed:
  - read_document(path): Read a file from the configured DOCS_DIR.
  - query(question):     Answer a question from the knowledge base.

Security decisions:
- DOCS_DIR is the ONLY directory from which files may be read.
- All paths are resolved to absolute form before any I/O, eliminating
  directory traversal sequences (e.g. '../../etc/passwd').
- is_relative_to() enforces the boundary even after symlink resolution.
- Only .txt, .md, and .pdf extensions are permitted; binary or sensitive
  file types (e.g. .env, .py, .db) are explicitly rejected.
- No credentials or secrets are hardcoded; all config comes from .env.
"""

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so src.* imports resolve correctly
# when this file is run directly (e.g. via `python mcp-servers/knowledge-server/server.py`)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.audit.logger import log_event
from src.query.engine import query_knowledge_base

load_dotenv()

# ---------------------------------------------------------------------------
# Server initialisation
# ---------------------------------------------------------------------------

mcp = FastMCP("knowledge-server")

# Security: resolve DOCS_DIR once at startup.
# .resolve() follows symlinks and returns the canonical absolute path, so
# subsequent is_relative_to() checks cannot be fooled by symlink traversal.
_DOCS_DIR_RAW = os.getenv("DOCS_DIR", "./docs")
DOCS_DIR: Path = Path(_DOCS_DIR_RAW).resolve()

# Permitted file extensions for read_document.
# Extending this set requires a deliberate code change — no dynamic config.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".pdf"})


# ---------------------------------------------------------------------------
# Path safety helper
# ---------------------------------------------------------------------------

def _safe_resolve(requested_path: str) -> Path:
    """
    Resolve a caller-supplied path relative to DOCS_DIR and verify that the
    result stays inside DOCS_DIR.

    Security: this is the central path-traversal defence.
    1. Joining with DOCS_DIR prevents absolute paths from escaping.
    2. .resolve() follows every symlink and eliminates all '..' components.
    3. is_relative_to() confirms the final path is still inside DOCS_DIR.

    If the resolved path escapes DOCS_DIR for any reason, a ValueError is
    raised immediately — no I/O is performed.
    """
    # Prevent callers from supplying an absolute path that bypasses DOCS_DIR
    if os.path.isabs(requested_path):
        raise ValueError(
            "Absolute paths are not permitted. "
            "Provide a path relative to the docs directory."
        )

    resolved = (DOCS_DIR / requested_path).resolve()

    # Security: is_relative_to() is the final gate.
    # Because both sides were resolved with .resolve(), symlink tricks cannot
    # construct a path that appears relative but points elsewhere.
    if not resolved.is_relative_to(DOCS_DIR):
        raise ValueError(
            f"Path traversal attempt blocked: '{requested_path}' resolves "
            f"outside the permitted docs directory."
        )

    return resolved


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
def read_document(path: str) -> str:
    """
    Read a document from the knowledge base directory.

    Args:
        path: Relative path to the document within the docs directory.
              Example: "policies/hr-handbook.pdf"

    Returns:
        The full text content of the document.
    """
    try:
        safe_path = _safe_resolve(path)

        if not safe_path.exists():
            raise FileNotFoundError(
                f"Document not found: '{path}'. "
                f"Check the path is relative to the docs directory."
            )

        if not safe_path.is_file():
            raise ValueError(f"'{path}' is not a file.")

        # Security: whitelist of permitted extensions.
        # Rejects .env, .py, .db, .key, and any other sensitive type.
        ext = safe_path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"File type '{ext}' is not permitted. "
                f"Allowed types: {sorted(ALLOWED_EXTENSIONS)}"
            )

        # Read content based on file type
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(safe_path))
            content = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        else:
            content = safe_path.read_text(encoding="utf-8", errors="replace")

        log_event(
            event_type="read_document",
            input_data=path,
            output_data=f"{len(content)} characters read",
            source_document=safe_path.name,
            success=True,
        )

        return content

    except (ValueError, FileNotFoundError) as exc:
        log_event(
            event_type="read_document",
            input_data=path,
            output_data=None,
            source_document=path,
            success=False,
            error=str(exc),
        )
        raise
    except Exception as exc:
        log_event(
            event_type="read_document",
            input_data=path,
            output_data=None,
            source_document=path,
            success=False,
            error=str(exc),
        )
        raise


@mcp.tool()
def query(question: str) -> str:
    """
    Answer a natural language question using the knowledge base.

    Retrieves relevant document chunks via semantic search and generates
    a grounded answer using Claude. The answer cites source documents.

    Args:
        question: The natural language question to answer.

    Returns:
        Answer text followed by source document attribution.
    """
    result = query_knowledge_base(question)

    if result["sources"]:
        sources_text = "\n\nSources: " + ", ".join(result["sources"])
    else:
        sources_text = "\n\nNo sources found."

    return result["answer"] + sources_text


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
