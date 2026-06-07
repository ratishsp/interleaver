"""Stage 1 — extract plain text from a book file.

Supports .txt, .epub, and .pdf. EPUB is preferred (cleanest text); PDF is the
messiest because of hyphenation and column layout, so we de-hyphenate it.
"""
from __future__ import annotations

import re
from pathlib import Path


def extract_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".txt":
        raw = path.read_text(encoding="utf-8")
    elif suffix == ".epub":
        raw = _extract_epub(path)
    elif suffix == ".pdf":
        raw = _extract_pdf(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix!r} (use .txt, .epub, or .pdf)")
    return _normalize(raw)


def _extract_epub(path: Path) -> str:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(str(path))
    chunks: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Block-level tags become paragraph breaks so sentences don't run together.
        for block in soup.find_all(["p", "div", "br", "h1", "h2", "h3", "h4", "li"]):
            block.append("\n\n")
        chunks.append(soup.get_text())
    return "\n".join(chunks)


def _extract_pdf(path: Path) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    text = "\n".join(page.get_text() for page in doc)
    # Join words split across line breaks by hyphenation: "exam-\nple" -> "example".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return text


def _normalize(text: str) -> str:
    """Collapse runaway whitespace but keep paragraph (blank-line) boundaries."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Soft-wrap newlines (single \n inside a paragraph) -> space.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()
