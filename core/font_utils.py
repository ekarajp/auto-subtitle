from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication


DEFAULT_FALLBACKS = (
    "Tahoma",
    "Noto Sans Thai",
    "Leelawadee UI",
    "Segoe UI",
    "Arial",
)

THAI_FALLBACKS = (
    "Tahoma",
    "Noto Sans Thai",
    "Leelawadee UI",
    "Cordia New",
    "Angsana New",
    "Arial",
    "Segoe UI",
)


@dataclass(slots=True)
class FontResolution:
    requested_family: str
    resolved_family: str
    fallback_used: bool


def resolve_font_family(preferred_family: str, sample_text: str = "") -> str:
    return resolve_font_details(preferred_family, sample_text).resolved_family


def resolve_font_details(preferred_family: str, sample_text: str = "") -> FontResolution:
    available = _available_families()
    if not available:
        resolved = preferred_family.strip() or "Tahoma"
        return FontResolution(preferred_family.strip(), resolved, resolved.casefold() != preferred_family.strip().casefold())

    preferred = _match_available_family(preferred_family, available)
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    elif preferred_family.strip():
        candidates.append(preferred_family.strip())

    fallback_pool = THAI_FALLBACKS if _contains_thai(sample_text) else DEFAULT_FALLBACKS
    for family in fallback_pool:
        matched = _match_available_family(family, available)
        if matched and matched not in candidates:
            candidates.append(matched)

    for family in candidates:
        if font_supports_text(family, sample_text):
            return FontResolution(preferred_family.strip(), family, family.casefold() != preferred_family.strip().casefold())

    resolved = candidates[0] if candidates else next(iter(available.values()))
    return FontResolution(preferred_family.strip(), resolved, resolved.casefold() != preferred_family.strip().casefold())


def font_supports_text(family: str, text: str) -> bool:
    if not text.strip():
        return True
    if QApplication.instance() is None:
        return True
    supported = {
        QFontDatabase.writingSystemName(system)
        for system in QFontDatabase.writingSystems(family)
    }
    if not supported:
        return True
    required = _required_writing_systems(text)
    return required.issubset(supported)


@lru_cache(maxsize=1)
def _available_families() -> dict[str, str]:
    if QApplication.instance() is None:
        return {}
    return {family.casefold(): family for family in QFontDatabase.families()}


def _match_available_family(name: str, available: dict[str, str]) -> str | None:
    cleaned = name.strip().casefold()
    if not cleaned:
        return None
    return available.get(cleaned)


def _contains_thai(text: str) -> bool:
    return any("\u0e00" <= char <= "\u0e7f" for char in text)


def _required_writing_systems(text: str) -> set[str]:
    required: set[str] = set()
    for char in text:
        if char.isspace() or _is_neutral_text_character(char):
            continue
        code = ord(char)
        if 0x0E00 <= code <= 0x0E7F:
            required.add("Thai")
        elif "A" <= char <= "Z" or "a" <= char <= "z" or "0" <= char <= "9":
            required.add("Latin")
        elif 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
            required.add("Arabic")
        elif 0x0900 <= code <= 0x097F:
            required.add("Devanagari")
        elif 0x4E00 <= code <= 0x9FFF:
            required.add("Simplified Chinese")
        elif 0x3040 <= code <= 0x30FF:
            required.add("Japanese")
        elif 0xAC00 <= code <= 0xD7AF:
            required.add("Korean")
    return required


def _is_neutral_text_character(char: str) -> bool:
    category = unicodedata.category(char)
    return category[0] in {"P", "S"} or category in {"Mn", "Mc", "Me"}
