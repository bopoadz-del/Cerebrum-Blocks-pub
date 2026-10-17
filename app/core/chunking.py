"""Simple paragraph-aware text chunking for the ingestion pipeline."""

import logging

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split ``text`` into chunks of at most ``chunk_size`` characters.

    Splits by paragraph boundaries first; paragraphs longer than
    ``chunk_size`` are split by words. Consecutive chunks overlap by
    ``chunk_overlap`` characters when possible.
    """
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []

    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            chunks.append(paragraph)
            continue

        words = paragraph.split()
        current: list[str] = []
        current_len = 0

        for word in words:
            separator = 1 if current else 0
            if current_len + separator + len(word) > chunk_size and current:
                chunks.append(" ".join(current))

                # Build an overlap window from the end of the current chunk.
                overlap: list[str] = []
                overlap_len = 0
                for w in reversed(current):
                    add = len(w) + (1 if overlap else 0)
                    if overlap_len + add > chunk_overlap:
                        break
                    overlap.insert(0, w)
                    overlap_len += add

                current = overlap
                current_len = overlap_len

            current.append(word)
            current_len += len(word) + (1 if len(current) > 1 else 0)

        if current:
            chunks.append(" ".join(current))

    return chunks
