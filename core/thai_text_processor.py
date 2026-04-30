from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


THAI_RE = re.compile(r"[\u0E00-\u0E7F]")
THAI_MARK_RE = re.compile(r"^[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]")
THAI_LEADING_VOWELS = {"เ", "แ", "โ", "ใ", "ไ"}
THAI_SOFT_BOUNDARIES = (
    "และ",
    "แล้ว",
    "แต่",
    "เพราะ",
    "เพราะว่า",
    "ใน",
    "ที่",
    "ซึ่ง",
    "หรือ",
    "ก็คือ",
    "คือ",
)


def contains_thai(text: str) -> bool:
    return bool(THAI_RE.search(text or ""))


def starts_with_thai_mark(text: str) -> bool:
    return bool(text and THAI_MARK_RE.match(text))


def likely_broken_thai_fragment(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or not contains_thai(stripped):
        return False
    if starts_with_thai_mark(stripped):
        return True
    if len(stripped) <= 2 and contains_thai(stripped):
        return True
    return bool(re.search(r"\s+[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]", stripped))


@lru_cache(maxsize=1024)
def thai_phrase_tokens(text: str) -> tuple[str, ...]:
    """Return Thai-safe tokens. Uses PyThaiNLP if available, with a safe fallback."""
    normalized = unicodedata.normalize("NFC", text or "")
    if not normalized:
        return ()
    try:
        from pythainlp.tokenize import word_tokenize

        tokens = [token.strip() for token in word_tokenize(normalized, engine="newmm") if token.strip()]
        if tokens:
            return tuple(_repair_tokens(tokens))
    except Exception:
        pass
    tokens = re.findall(
        r"[\u0E00-\u0E7F]+(?:\u0E46)?|[A-Za-z0-9]+|[^\s\u0E00-\u0E7FA-Za-z0-9]",
        normalized,
    )
    return tuple(_repair_tokens(tokens))


def natural_text_chunks(text: str, *, max_chars: int, max_chunks: int | None = None) -> list[str]:
    """Split text at sentence/phrase boundaries without breaking Thai words."""
    cleaned = unicodedata.normalize("NFC", text or "").strip()
    if not cleaned:
        return []
    max_chars = max(8, max_chars)

    first_pass = _split_by_strong_boundaries(cleaned)
    chunks: list[str] = []
    for part in first_pass:
        chunks.extend(_split_long_part(part, max_chars=max_chars))

    if max_chunks and len(chunks) > max_chunks:
        chunks = _merge_to_limit(chunks, max_chunks=max_chunks)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _split_by_strong_boundaries(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    if len(parts) > 1:
        return [part.strip() for part in parts if part.strip()]
    return [text]


def _split_long_part(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    if contains_thai(text):
        boundary_chunks = _split_thai_soft_boundaries(text, max_chars=max_chars)
        if len(boundary_chunks) > 1:
            chunks: list[str] = []
            for chunk in boundary_chunks:
                chunks.extend(_split_long_part(chunk, max_chars=max_chars))
            return chunks

    tokens = list(thai_phrase_tokens(text)) if contains_thai(text) else text.split()
    if not tokens:
        return [text]

    chunks: list[str] = []
    current = ""
    for token in tokens:
        candidate = _join_token(current, token)
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = token
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text]


def _split_thai_soft_boundaries(text: str, *, max_chars: int) -> list[str]:
    tokens = list(thai_phrase_tokens(text))
    if len(tokens) < 3:
        return [text]

    chunks: list[str] = []
    current = ""
    for token in tokens:
        is_boundary = token in THAI_SOFT_BOUNDARIES
        if current and is_boundary and len(current) >= max_chars * 0.55:
            chunks.append(current)
            current = token
            continue
        candidate = _join_token(current, token)
        if current and len(candidate) > max_chars * 1.20:
            chunks.append(current)
            current = token
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text]


def _join_token(current: str, token: str) -> str:
    if not current:
        return token
    if contains_thai(current) and contains_thai(token):
        return current + token
    if token in ".,:;!?)]}":
        return current + token
    return f"{current} {token}"


def _merge_to_limit(chunks: list[str], *, max_chunks: int) -> list[str]:
    merged = list(chunks[:max_chunks])
    for chunk in chunks[max_chunks:]:
        shortest_index = min(range(len(merged)), key=lambda index: len(merged[index]))
        merged[shortest_index] = f"{merged[shortest_index]} {chunk}".strip()
    return merged


def _repair_tokens(tokens: list[str]) -> list[str]:
    repaired: list[str] = []
    for token in tokens:
        if not token:
            continue
        if repaired and (
            starts_with_thai_mark(token)
            or (token[0] in THAI_LEADING_VOWELS and contains_thai(repaired[-1]) and len(repaired[-1]) <= 1)
        ):
            repaired[-1] += token
        else:
            repaired.append(token)
    return repaired
