"""
Integration hooks for wiki builder into the main pipeline.
Adds wiki synthesis as a post-download step.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.wiki_builder import synthesize_batch
from src import REPO_ROOT

LOGGER = logging.getLogger(__name__)
WIKI_DIR = REPO_ROOT / "wiki"


def prepare_documents_for_wiki(
    downloaded_items: list[dict[str, Any]],
    content_loader=None,
) -> list[dict[str, Any]]:
    """
    Convert downloaded documents to wiki format.
    Loads actual file content for synthesis.

    Args:
        downloaded_items: List of download results with file_path, doc_id, etc.
        content_loader: Optional function(file_path) -> content. Defaults to read file.

    Returns:
        List of dicts ready for synthesize_batch()
    """
    if content_loader is None:
        def content_loader(path: str) -> str:
            try:
                p = Path(path)
                if p.exists() and p.is_file():
                    # Try text first, fall back to binary for PDFs
                    try:
                        return p.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        return ""  # PDF or binary - would need extraction
                return ""
            except Exception as exc:
                LOGGER.warning("Could not load content from %s: %s", path, exc)
                return ""

    docs = []
    for item in downloaded_items:
        if not item.get("file_path") or item.get("download_status") != "Downloaded":
            continue

        content = content_loader(item["file_path"])
        if not content or len(content) < 200:
            continue

        docs.append(
            {
                "doc_id": item.get("doc_id"),
                "doc_title": item.get("document_name") or item.get("ddg_title") or "Untitled",
                "url": item.get("url"),
                "content": content,
                "company_name": item.get("company_name"),
                "source_backend": item.get("source_backend"),
                "file_type": item.get("file_type"),
            }
        )

    return docs


def synthesize_downloaded_batch(
    downloaded_items: list[dict[str, Any]],
    wiki_dir: Path = WIKI_DIR,
    llm_model: str = "mistral",
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Main entry point: take downloaded results and synthesize into wiki.

    Usage in main.py after download_entries():
        wiki_results = synthesize_downloaded_batch(
            downloaded_results,
            llm_model="mistral"
        )

    Args:
        downloaded_items: Results from download_entries()
        wiki_dir: Path to wiki root
        llm_model: Local LLM model (mistral, neural-chat, llama2, etc.)
        dry_run: If True, only report what would be synthesized, don't write

    Returns:
        Batch results with entity counts, pages updated, etc.
    """
    wiki_dir.mkdir(parents=True, exist_ok=True)

    docs = prepare_documents_for_wiki(downloaded_items)
    if not docs:
        LOGGER.info("No documents to synthesize for wiki")
        return {
            "total_documents": len(downloaded_items),
            "prepared_documents": 0,
            "status": "skipped_no_content",
        }

    LOGGER.info("Synthesizing %s documents into wiki using %s", len(docs), llm_model)

    if dry_run:
        LOGGER.info("DRY RUN: Would synthesize %s documents", len(docs))
        return {
            "total_documents": len(docs),
            "status": "dry_run",
            "dry_run": True,
        }

    try:
        results = synthesize_batch(docs, wiki_dir=wiki_dir, llm_model=llm_model)
        LOGGER.info(
            "Wiki synthesis complete: %s processed, %s entities, %s pages updated",
            results.get("processed"),
            results.get("total_entities"),
            results.get("pages_updated"),
        )
        return results
    except Exception as exc:
        LOGGER.error("Wiki synthesis failed: %s", exc)
        return {
            "status": "failed",
            "error": str(exc),
        }


def get_wiki_summary(wiki_dir: Path = WIKI_DIR) -> dict[str, Any]:
    """Get summary stats about current wiki state."""
    if not wiki_dir.exists():
        return {"status": "wiki_not_found", "entity_count": 0}

    entity_counts = {
        "companies": len(list(wiki_dir.glob("companies/*.md"))),
        "facilities": len(list(wiki_dir.glob("facilities/*.md"))),
        "investments": len(list(wiki_dir.glob("investments/*.md"))),
        "relationships": len(list(wiki_dir.glob("relationships/*.md"))),
    }

    return {
        "status": "ok",
        "wiki_path": str(wiki_dir),
        "entity_counts": entity_counts,
        "total_entities": sum(entity_counts.values()),
    }
