"""Stage 2 — split text into sentences, per language.

Uses `sentence-splitter` (Koehn/Schenk rule-based, no model download) which
supports both Danish ('da') and English ('en'). We split paragraph-by-paragraph
so a missing period at a paragraph end can't glue two sentences together.
"""
from __future__ import annotations


def split_sentences(text: str, lang: str) -> list[str]:
    from sentence_splitter import SentenceSplitter

    splitter = SentenceSplitter(language=lang)
    sentences: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        for sent in splitter.split(para):
            sent = sent.strip()
            if sent:
                sentences.append(sent)
    return sentences
