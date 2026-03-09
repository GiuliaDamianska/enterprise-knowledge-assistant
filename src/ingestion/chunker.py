"""
Document chunker — splits text and PDF files into overlapping chunks.

Chunking strategy:
- Fixed-size character windows with overlap to preserve context at boundaries.
- Overlap ensures that sentences or paragraphs split across a boundary are
  still retrievable by queries that match either side.
"""

from pathlib import Path

# Chunk size in characters. ~800 chars ≈ 150–200 words, which fits well
# within the context window of embedding models while remaining semantically
# coherent for most document types.
CHUNK_SIZE = 800

# Overlap in characters. 100 chars ≈ 1–2 sentences, enough to bridge
# context across chunk boundaries without doubling storage costs.
CHUNK_OVERLAP = 100


def _read_text(path: Path) -> str:
    """Read a plain text or Markdown file."""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    """
    Extract text from a PDF using pypdf.

    Security: pypdf processes the file in-memory without executing any
    embedded scripts or JavaScript. Malformed PDFs raise exceptions rather
    than executing arbitrary code.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ImportError(
            "pypdf is required for PDF support. Install with: pip install pypdf"
        ) from exc

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def extract_text(path: Path) -> str:
    """
    Extract raw text from a supported file type.

    Supported: .txt, .md, .pdf
    Raises ValueError for unsupported extensions.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix in {".txt", ".md"}:
        return _read_text(path)
    raise ValueError(
        f"Unsupported file type '{suffix}'. Supported: .txt, .md, .pdf"
    )


def chunk_text(text: str, source: str) -> list[dict]:
    """
    Split text into overlapping fixed-size chunks.

    Returns a list of dicts, each with:
      - 'text':        the chunk content
      - 'source':      the originating file name
      - 'chunk_index': zero-based position within the document
    """
    chunks = []
    start = 0
    idx = 0

    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]

        # Skip whitespace-only chunks that carry no information
        if chunk.strip():
            chunks.append(
                {
                    "text": chunk,
                    "source": source,
                    "chunk_index": idx,
                }
            )
            idx += 1

        # Advance by (CHUNK_SIZE - CHUNK_OVERLAP) to create the sliding window
        start = end - CHUNK_OVERLAP

    return chunks
