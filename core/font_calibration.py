from __future__ import annotations

import json
import unicodedata
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


CALIBRATION_FILE = Path(__file__).resolve().parent.parent / "config" / "font_calibration_profiles.json"


@dataclass(slots=True)
class FontCalibrationProfile:
    family: str = "*"
    script: str = "generic"
    style_key: str = "*"
    size_scale: float = 0.40
    baseline_offset: float = -0.035
    line_height_scale: float = 1.0
    y_offset: float = 0.0
    x_offset: float = 0.0
    wrap_width_adjustment: float = 0.0
    bbox_padding_adjustment: float = 0.0
    ascent_adjustment: float = 0.0
    descent_adjustment: float = 0.0
    stretch: int = 100
    path_scale_x: float = 1.0
    path_scale_y: float = 1.0

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "FontCalibrationProfile":
        return cls(
            family=str(payload.get("family", "*") or "*"),
            script=str(payload.get("script", "generic") or "generic"),
            style_key=str(payload.get("style_key", "*") or "*"),
            size_scale=float(payload.get("size_scale", 0.40) or 0.40),
            baseline_offset=float(payload.get("baseline_offset", -0.035) or 0.0),
            line_height_scale=float(payload.get("line_height_scale", 1.0) or 1.0),
            y_offset=float(payload.get("y_offset", 0.0) or 0.0),
            x_offset=float(payload.get("x_offset", 0.0) or 0.0),
            wrap_width_adjustment=float(payload.get("wrap_width_adjustment", 0.0) or 0.0),
            bbox_padding_adjustment=float(payload.get("bbox_padding_adjustment", 0.0) or 0.0),
            ascent_adjustment=float(payload.get("ascent_adjustment", 0.0) or 0.0),
            descent_adjustment=float(payload.get("descent_adjustment", 0.0) or 0.0),
            stretch=int(payload.get("stretch", 100) or 100),
            path_scale_x=float(payload.get("path_scale_x", 1.0) or 1.0),
            path_scale_y=float(payload.get("path_scale_y", 1.0) or 1.0),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


DEFAULT_PROFILES: tuple[FontCalibrationProfile, ...] = (
    FontCalibrationProfile(),
    FontCalibrationProfile(family="*", script="latin", size_scale=0.82, baseline_offset=-0.08, path_scale_y=1.25),
    FontCalibrationProfile(family="*", script="mixed", size_scale=0.76, baseline_offset=0.04, path_scale_y=1.26),
    FontCalibrationProfile(
        family="Arial", script="latin", size_scale=0.88, baseline_offset=-0.14, stretch=94, path_scale_y=1.35
    ),
    FontCalibrationProfile(
        family="Arial", script="mixed", size_scale=0.82, baseline_offset=-0.04, stretch=94, path_scale_y=1.28
    ),
    FontCalibrationProfile(
        family="Segoe UI", script="latin", size_scale=0.80, baseline_offset=-0.10, stretch=94, path_scale_y=1.25
    ),
    FontCalibrationProfile(
        family="Segoe UI", script="mixed", size_scale=0.69, baseline_offset=0.08, path_scale_y=1.28
    ),
    FontCalibrationProfile(
        family="Tahoma", script="latin", size_scale=0.88, baseline_offset=-0.05, stretch=96, path_scale_y=1.20
    ),
    FontCalibrationProfile(
        family="Tahoma", script="mixed", size_scale=0.84, baseline_offset=0.08, path_scale_y=1.26
    ),
    FontCalibrationProfile(family="Noto Sans Thai", script="latin", size_scale=0.44),
    FontCalibrationProfile(family="Leelawadee UI", script="latin", size_scale=0.44),
    FontCalibrationProfile(family="Prompt", script="latin", size_scale=0.68, baseline_offset=0.07, path_scale_y=0.97),
    FontCalibrationProfile(
        family="Prompt", script="mixed", size_scale=0.66, baseline_offset=-0.005, x_offset=0.04, path_scale_x=1.03
    ),
    FontCalibrationProfile(family="Prompt Medium", script="latin", size_scale=0.68, baseline_offset=0.07, path_scale_y=0.97),
    FontCalibrationProfile(family="Angsana New", script="latin", size_scale=0.76, baseline_offset=0.0, path_scale_y=1.20),
    FontCalibrationProfile(family="Cordia New", script="latin", size_scale=0.70, baseline_offset=0.0, path_scale_y=1.20),
    FontCalibrationProfile(family="*", script="thai", size_scale=0.73, path_scale_y=1.28),
    FontCalibrationProfile(family="Tahoma", script="thai", size_scale=0.84, path_scale_y=1.26),
    FontCalibrationProfile(family="Noto Sans Thai", script="thai", size_scale=0.69, path_scale_y=1.28),
    FontCalibrationProfile(family="Leelawadee UI", script="thai", size_scale=0.78, path_scale_y=1.15),
    FontCalibrationProfile(family="Arial", script="thai", size_scale=0.69, path_scale_y=1.28),
    FontCalibrationProfile(family="Segoe UI", script="thai", size_scale=0.69, path_scale_y=1.28),
    FontCalibrationProfile(family="Prompt", script="thai", size_scale=0.66, baseline_offset=-0.005),
    FontCalibrationProfile(family="*", script="cjk", size_scale=0.74),
    FontCalibrationProfile(family="*", script="arabic", size_scale=0.70),
    FontCalibrationProfile(family="*", script="devanagari", size_scale=0.72),
)


_PROFILE_OVERRIDES: dict[tuple[str, str, str], FontCalibrationProfile] = {}
_FILE_PROFILE_CACHE: dict[tuple[str, str, str], FontCalibrationProfile] | None = None
_FAMILY_STYLE_SUFFIXES = (
    "black",
    "extrabold",
    "extra bold",
    "bold",
    "semibold",
    "semi bold",
    "medium",
    "extralight",
    "extra light",
    "light",
    "thin",
    "italic",
)


def detect_script_category(text: str) -> str:
    has_latin = False
    has_other = False
    categories: set[str] = set()
    for char in text:
        if char.isspace():
            continue
        code = ord(char)
        if 0x0E00 <= code <= 0x0E7F:
            categories.add("thai")
        elif 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
            categories.add("cjk")
        elif 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
            categories.add("arabic")
        elif 0x0900 <= code <= 0x097F:
            categories.add("devanagari")
        elif "A" <= char <= "Z" or "a" <= char <= "z" or "0" <= char <= "9":
            has_latin = True
        elif _is_neutral_script_character(char):
            continue
        else:
            has_other = True
    if len(categories) == 1 and not has_latin and not has_other:
        return next(iter(categories))
    if categories:
        return "mixed"
    if has_latin:
        return "latin"
    if has_other:
        return "generic"
    return "generic"


def _is_neutral_script_character(char: str) -> bool:
    category = unicodedata.category(char)
    return category[0] in {"P", "S"} or category in {"Mn", "Mc", "Me"}


def _script_lookup_keys(text: str) -> list[str]:
    detected = detect_script_category(text)
    if detected != "mixed":
        return [detected]

    counts: dict[str, int] = {}
    for char in text:
        script = _character_script(char)
        if script:
            counts[script] = counts.get(script, 0) + 1

    non_latin = [key for key in counts if key != "latin"]
    ordered = sorted(non_latin, key=lambda key: (-counts[key], key))
    if "latin" in counts:
        ordered.append("latin")
    keys = ["mixed"] + ordered
    unique: list[str] = []
    for key in keys:
        if key not in unique:
            unique.append(key)
    return unique or ["mixed"]


def _character_script(char: str) -> str | None:
    if char.isspace() or _is_neutral_script_character(char):
        return None
    code = ord(char)
    if 0x0E00 <= code <= 0x0E7F:
        return "thai"
    if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
        return "cjk"
    if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
        return "arabic"
    if 0x0900 <= code <= 0x097F:
        return "devanagari"
    if "A" <= char <= "Z" or "a" <= char <= "z" or "0" <= char <= "9":
        return "latin"
    return None


def resolve_font_calibration(family: str, sample_text: str = "", style_key: str = "*") -> FontCalibrationProfile:
    resolved_family = family.strip() or "*"
    profiles = _combined_profiles()
    style_key = _normalize_style_key(style_key)
    family_keys = _family_lookup_keys(resolved_family)
    script_keys = _script_lookup_keys(sample_text)
    search_order = [
        *[
            (family_key, script_key, style_key)
            for script_key in script_keys
            for family_key in family_keys
        ],
        *[
            (family_key, script_key, "*")
            for script_key in script_keys
            for family_key in family_keys
        ],
        *[(family_key, "generic", style_key) for family_key in family_keys],
        *[(family_key, "generic", "*") for family_key in family_keys],
        *[("*", script_key, style_key) for script_key in script_keys],
        *[("*", script_key, "*") for script_key in script_keys],
        ("*", "generic", style_key),
        ("*", "generic", "*"),
    ]
    for key in search_order:
        profile = profiles.get(key)
        if profile:
            return profile
    return FontCalibrationProfile()


def calibration_debug_summary(family: str, sample_text: str = "", style_key: str = "*") -> dict[str, object]:
    profile = resolve_font_calibration(family, sample_text, style_key)
    return {
        "family": family,
        "script": detect_script_category(sample_text),
        "style_key": _normalize_style_key(style_key),
        "profile": profile.to_dict(),
    }


def save_font_calibration_profiles(profiles: list[FontCalibrationProfile]) -> Path:
    existing = _load_file_profiles()
    for profile in profiles:
        profile.style_key = _normalize_style_key(profile.style_key)
        existing[(profile.family.casefold(), profile.script, profile.style_key)] = profile
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = [profile.to_dict() for profile in existing.values()]
    CALIBRATION_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    global _FILE_PROFILE_CACHE
    _FILE_PROFILE_CACHE = dict(existing)
    return CALIBRATION_FILE


def load_font_calibration_profiles() -> list[FontCalibrationProfile]:
    return list(_combined_profiles().values())


def set_profile_override(profile: FontCalibrationProfile) -> None:
    profile.style_key = _normalize_style_key(profile.style_key)
    _PROFILE_OVERRIDES[(profile.family.casefold(), profile.script, profile.style_key)] = profile


def clear_profile_overrides() -> None:
    _PROFILE_OVERRIDES.clear()


@contextmanager
def temporary_profile_overrides(profiles: list[FontCalibrationProfile]) -> Iterator[None]:
    previous = dict(_PROFILE_OVERRIDES)
    try:
        for profile in profiles:
            set_profile_override(profile)
        yield
    finally:
        _PROFILE_OVERRIDES.clear()
        _PROFILE_OVERRIDES.update(previous)


def _combined_profiles() -> dict[tuple[str, str, str], FontCalibrationProfile]:
    profiles: dict[tuple[str, str, str], FontCalibrationProfile] = {
        (profile.family.casefold(), profile.script, _normalize_style_key(profile.style_key)): profile
        for profile in DEFAULT_PROFILES
    }
    profiles.update(_load_file_profiles())
    profiles.update(_PROFILE_OVERRIDES)
    return profiles


def _load_file_profiles() -> dict[tuple[str, str, str], FontCalibrationProfile]:
    global _FILE_PROFILE_CACHE
    if _FILE_PROFILE_CACHE is not None:
        return dict(_FILE_PROFILE_CACHE)
    if not CALIBRATION_FILE.exists():
        _FILE_PROFILE_CACHE = {}
        return {}
    try:
        payload = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    except Exception:
        _FILE_PROFILE_CACHE = {}
        return {}
    if not isinstance(payload, list):
        _FILE_PROFILE_CACHE = {}
        return {}
    cache: dict[tuple[str, str, str], FontCalibrationProfile] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        profile = FontCalibrationProfile.from_dict(item)
        profile.style_key = _normalize_style_key(profile.style_key)
        cache[(profile.family.casefold(), profile.script, profile.style_key)] = profile
    _FILE_PROFILE_CACHE = cache
    return dict(cache)


def _normalize_style_key(style_key: str) -> str:
    cleaned = (style_key or "*").strip()
    return cleaned if cleaned else "*"


def _family_lookup_keys(family: str) -> list[str]:
    cleaned = (family or "*").strip()
    if not cleaned or cleaned == "*":
        return ["*"]
    exact = cleaned.casefold()
    base = _canonical_family_name(cleaned).casefold()
    keys = [exact]
    if base and base not in keys:
        keys.append(base)
    return keys


def _canonical_family_name(family: str) -> str:
    words = family.replace("-", " ").split()
    if not words:
        return family.strip()
    trimmed = list(words)
    while trimmed:
        suffix = " ".join(trimmed[-2:]).casefold() if len(trimmed) >= 2 else ""
        last = trimmed[-1].casefold()
        if suffix in _FAMILY_STYLE_SUFFIXES:
            trimmed = trimmed[:-2]
            continue
        if last in _FAMILY_STYLE_SUFFIXES:
            trimmed = trimmed[:-1]
            continue
        break
    return " ".join(trimmed).strip() or family.strip()
