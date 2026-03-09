"""
CLI ingestion script — ingest all documents in DOCS_DIR into ChromaDB.

Usage:
    uv run python scripts/ingest.py
    uv run python scripts/ingest.py --dir /path/to/docs
    uv run python scripts/ingest.py --file /path/to/docs/report.pdf
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from src.ingestion.pipeline import ingest_directory, ingest_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest documents into the enterprise knowledge base."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dir",
        type=Path,
        help="Directory to ingest (defaults to DOCS_DIR env var)",
    )
    group.add_argument(
        "--file",
        type=Path,
        help="Single file to ingest",
    )
    args = parser.parse_args()

    if args.file:
        if not args.file.exists():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        print(f"Ingesting {args.file} ...")
        n = ingest_file(args.file)
        print(f"Done. {n} chunks stored.")
    else:
        print(f"Ingesting directory: {args.dir or '(from DOCS_DIR env var)'}")
        results = ingest_directory(args.dir)
        print(
            f"Done. Files processed: {results['processed']}, "
            f"chunks stored: {results['chunks']}"
        )
        if results["errors"]:
            print(f"\nErrors ({len(results['errors'])}):")
            for err in results["errors"]:
                print(f"  {err['file']}: {err['error']}")
            sys.exit(1)


if __name__ == "__main__":
    main()
