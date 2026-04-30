from __future__ import annotations

import re
import unicodedata


_SPACE_RE = re.compile(r"[ \t\r\f\v]+")


def normalize_source_text(text: str) -> str:
    """Normalize user-provided subtitle text without rewriting its wording."""
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACE_RE.sub(" ", line).strip() for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_asr_text(text: str, *, cleanup_noise: bool = True) -> str:
    """Clean ASR text conservatively. This must not be used to replace source text."""
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.replace("\r", " ").replace("\n", " ")
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    if cleanup_noise:
        normalized = _drop_obvious_asr_noise(normalized)
    return normalized.strip()


def compact_text_identity(text: str) -> str:
    """Identity string for validating that source text survived sync."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text or ""))


def visible_character_count(text: str) -> int:
    return len(compact_text_identity(text))


def _drop_obvious_asr_noise(text: str) -> str:
    # Keep this intentionally conservative. Aggressive cleanup can damage Thai.
    text = re.sub(r"\[(?:music|applause|noise|silence)\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\((?:music|applause|noise|silence)\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(\S)\1{8,}", r"\1\1", text)
    return _SPACE_RE.sub(" ", text)
