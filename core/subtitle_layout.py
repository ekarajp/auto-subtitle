from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from core.font_calibration import resolve_font_calibration
from core.font_utils import resolve_font_family
from core.style_preset import SubtitleStyle, effective_bottom_margin, effective_horizontal_margin
from core.video_info import VideoInfo


# Single source of truth for subtitle layout.
#
# FFmpeg/libass and Qt do not rasterize the same font at the same numeric size.
# Keep the renderer calibration here so both preview and export still read from
# one positioning model while using renderer-specific glyph scaling.
WRAP_FONT_SCALE = 1.45
ASS_FONT_SCALE = 2.05
ASS_Y_OFFSET_LINE_FACTOR = -0.10
PREVIEW_Y_OFFSET_LINE_FACTOR = ASS_Y_OFFSET_LINE_FACTOR
PREVIEW_STROKE_SCALE = 1.00


def style_for_preview(style: SubtitleStyle, sample_text: str = "") -> SubtitleStyle:
    copied = style_for_ass_export(style)
    copied.font_family = resolve_font_family(copied.font_family, sample_text)
    copied.font_size = max(1, round(copied.font_size * preview_font_scale(style, sample_text)))
    copied.line_spacing = 0
    return copied


def style_for_ass_export(style: SubtitleStyle) -> SubtitleStyle:
    copied = SubtitleStyle.from_dict(style.to_dict())
    copied.font_family = resolve_font_family(copied.font_family, "")
    copied.font_size = max(1, round(copied.font_size * ASS_FONT_SCALE))
    copied.line_spacing = round(copied.line_spacing * ASS_FONT_SCALE)
    return copied


def wrap_subtitle_text(
    text: str,
    video_info: VideoInfo,
    style: SubtitleStyle,
    *,
    limit_lines: bool = True,
) -> list[str]:
    source_lines = [line.strip() for line in text.replace("\\n", "\n").splitlines() if line.strip()]
    if not source_lines:
        return [""]

    resolved_family = resolve_font_family(style.font_family, text)
    calibration = resolve_font_calibration(resolved_family, text, style_calibration_key(style))
    max_width_px = video_info.width * max(20, min(style.max_width_percent, 100)) / 100
    visual_font_px = max(1.0, style.font_size * WRAP_FONT_SCALE * (1.0 + calibration.wrap_width_adjustment))
    max_width_units = max(4.0, max_width_px / visual_font_px)

    wrapped: list[str] = []
    for source in source_lines:
        wrapped.extend(_wrap_one_line(source, max_width_units))

    max_lines = max(1, style.max_lines)
    if limit_lines and len(wrapped) > max_lines:
        kept = wrapped[:max_lines]
        kept[-1] = _truncate_text(kept[-1], max_width_units)
        return kept
    return wrapped


def subtitle_line_positions(
    video_info: VideoInfo,
    style: SubtitleStyle,
    line_count: int,
    *,
    renderer: str,
) -> list[tuple[int, int, int]]:
    line_count = max(1, line_count)
    margin = effective_bottom_margin(video_info, style)
    safe_x = effective_horizontal_margin(video_info, style)
    line_height = subtitle_line_height(style)
    block_height = line_height * line_count

    if style.text_position == "custom":
        base_x = round(video_info.width * style.custom_x_percent / 100)
        base_y = round(video_info.height * style.custom_y_percent / 100)
        block_top = base_y - (block_height / 2)
    else:
        if style.alignment == "top_center":
            block_top = margin
        elif style.alignment == "center":
            block_top = (video_info.height / 2) - (block_height / 2)
        else:
            block_top = video_info.height - margin - block_height

        if style.alignment.endswith("_left"):
            base_x = safe_x
        elif style.alignment.endswith("_right"):
            base_x = video_info.width - safe_x
        else:
            base_x = round(video_info.width / 2)

    ass_alignment = 5
    if style.alignment.endswith("_left"):
        ass_alignment = 4
    elif style.alignment.endswith("_right"):
        ass_alignment = 6

    y_offset = 0.0
    if renderer == "ass":
        y_offset = line_height * ASS_Y_OFFSET_LINE_FACTOR
    elif renderer == "preview":
        y_offset = line_height * PREVIEW_Y_OFFSET_LINE_FACTOR

    positions = []
    for idx in range(line_count):
        y = block_top + (idx * line_height) + (line_height / 2) + y_offset
        y = max(8, min(video_info.height - 8, y))
        x = max(8, min(video_info.width - 8, base_x))
        positions.append((round(x), round(y), ass_alignment))
    return positions


def subtitle_line_height(style: SubtitleStyle) -> int:
    return max(1, round(style.font_size * 1.18 + style.line_spacing))


def subtitle_max_width(video_info: VideoInfo, style: SubtitleStyle) -> int:
    return round(video_info.width * max(20, min(style.max_width_percent, 100)) / 100)


def preview_baseline_shift(font_size: int, style: SubtitleStyle, sample_text: str = "") -> int:
    resolved_family = resolve_font_family(style.font_family, sample_text)
    calibration = resolve_font_calibration(resolved_family, sample_text, style_calibration_key(style))
    return round(font_size * calibration.baseline_offset)


def preview_stroke_width(stroke_width: float, scale_y: float) -> int:
    return max(1, round(stroke_width * scale_y * PREVIEW_STROKE_SCALE))


def preview_font_scale(style: SubtitleStyle, sample_text: str = "") -> float:
    resolved_family = resolve_font_family(style.font_family, sample_text)
    calibration = resolve_font_calibration(resolved_family, sample_text, style_calibration_key(style))
    return calibration.size_scale


def preview_font_stretch(style: SubtitleStyle, sample_text: str = "") -> int:
    resolved_family = resolve_font_family(style.font_family, sample_text)
    calibration = resolve_font_calibration(resolved_family, sample_text, style_calibration_key(style))
    return max(50, min(200, calibration.stretch))


def preview_font_path_scale(style: SubtitleStyle, sample_text: str = "") -> tuple[float, float]:
    resolved_family = resolve_font_family(style.font_family, sample_text)
    calibration = resolve_font_calibration(resolved_family, sample_text, style_calibration_key(style))
    return calibration.path_scale_x, calibration.path_scale_y


def preview_font_vertical_nudge(style: SubtitleStyle, sample_text: str, pixel_size: int) -> int:
    resolved_family = resolve_font_family(style.font_family, sample_text)
    calibration = resolve_font_calibration(resolved_family, sample_text, style_calibration_key(style))
    return round(max(1, pixel_size) * calibration.y_offset)


def preview_font_x_offset(style: SubtitleStyle, sample_text: str, pixel_size: int) -> int:
    resolved_family = resolve_font_family(style.font_family, sample_text)
    calibration = resolve_font_calibration(resolved_family, sample_text, style_calibration_key(style))
    return round(max(1, pixel_size) * calibration.x_offset)


def preview_line_height_scale(style: SubtitleStyle, sample_text: str = "") -> float:
    resolved_family = resolve_font_family(style.font_family, sample_text)
    calibration = resolve_font_calibration(resolved_family, sample_text, style_calibration_key(style))
    return calibration.line_height_scale


def style_calibration_key(style: SubtitleStyle) -> str:
    stroke = "stroke:on" if style.stroke_enabled and style.stroke_width > 0 else "stroke:off"
    if style.stroke_enabled and style.stroke_width > 0:
        stroke_bucket = round(min(12.0, max(0.0, float(style.stroke_width))) * 2) / 2
        stroke = f"stroke:{stroke_bucket:g}"
    shadow = "shadow:on" if style.shadow_enabled and style.shadow_offset > 0 else "shadow:off"
    background = "bg:on" if style.background_enabled else "bg:off"
    return f"{stroke}|{shadow}|{background}"


def _wrap_one_line(text: str, max_width_units: float) -> list[str]:
    if _text_width_units(text) <= max_width_units:
        return [text]

    lines: list[str] = []
    current = ""
    for word in _word_tokens(text):
        if not current:
            if _text_width_units(word) > max_width_units and not _contains_thai(word):
                lines.extend(_split_long_token_by_width(word, max_width_units))
                continue
            current = word
            continue

        candidate = _join_tokens(current, word)
        if _text_width_units(candidate) <= max_width_units:
            current = candidate
            continue
        if _text_width_units(word) > max_width_units:
            if current:
                lines.append(current)
                current = ""
            lines.extend(_split_long_token_by_width(word, max_width_units))
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _text_width_units(text: str) -> float:
    return sum(_char_width_units(char) for char in text)


def _char_width_units(char: str) -> float:
    if _is_combining_mark(char):
        return 0.0
    if char.isspace():
        return 0.32
    code = ord(char)
    if 0x0E00 <= code <= 0x0E7F:
        return 0.62
    if "A" <= char <= "Z":
        return 0.64
    if "a" <= char <= "z" or "0" <= char <= "9":
        return 0.54
    if char in ".,:;!?'\"-()[]{}":
        return 0.34
    if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
        return 0.95
    return 0.58


def _split_long_token_by_width(text: str, max_width_units: float) -> list[str]:
    if _contains_thai(text):
        tokens = _thai_word_tokens(text)
        if len(tokens) > 1:
            chunks: list[str] = []
            current = ""
            for token in tokens:
                candidate = current + token if current else token
                if _text_width_units(candidate) <= max_width_units:
                    current = candidate
                else:
                    if current:
                        chunks.append(current)
                    current = token
            if current:
                chunks.append(current)
            return chunks
        return [text]

    chunks: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width_units(candidate) > max_width_units and not _is_combining_mark(char):
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _word_tokens(text: str) -> list[str]:
    if " " in text:
        tokens: list[str] = []
        for part in text.split():
            if _contains_thai(part):
                tokens.extend(_thai_word_tokens(part))
            else:
                tokens.append(part)
        return tokens
    if _contains_thai(text):
        return _thai_word_tokens(text)
    return _split_long_token(text, 18)


def _join_tokens(current: str, token: str) -> str:
    if _contains_thai(current) and _contains_thai(token):
        return current + token
    return current + " " + token


def _contains_thai(text: str) -> bool:
    return any("\u0e00" <= char <= "\u0e7f" for char in text)


@lru_cache(maxsize=512)
def _thai_word_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text)
    try:
        from pythainlp.tokenize import word_tokenize

        tokens = [token.strip() for token in word_tokenize(normalized, engine="newmm") if token.strip()]
        if tokens:
            return _repair_thai_tokens(tokens)
    except Exception:
        pass

    tokens = re.findall(
        r"(?:[\u0E00-\u0E7F]+(?:\u0E46)?|[A-Za-z0-9]+|[^\s\u0E00-\u0E7FA-Za-z0-9])",
        normalized,
    )
    return _repair_thai_tokens(tokens)


def _repair_thai_tokens(tokens: list[str]) -> list[str]:
    repaired: list[str] = []
    for token in tokens:
        if not token:
            continue
        if repaired and (
            _starts_with_thai_mark(token)
            or (_looks_like_split_thai_tail(token) and _contains_thai(repaired[-1]) and len(repaired[-1]) <= 1)
        ):
            repaired[-1] += token
        else:
            repaired.append(token)
    return repaired


def _starts_with_thai_mark(token: str) -> bool:
    first = token[0]
    return first == "\u0E31" or "\u0E34" <= first <= "\u0E3A" or "\u0E47" <= first <= "\u0E4E"


def _looks_like_split_thai_tail(token: str) -> bool:
    return token[0] in {"\u0E30", "\u0E32", "\u0E33", "\u0E40", "\u0E41", "\u0E42", "\u0E43", "\u0E44"}


def _split_long_token(text: str, max_chars: int) -> list[str]:
    if _contains_thai(text):
        tokens = _thai_word_tokens(text)
        if len(tokens) > 1:
            chunks: list[str] = []
            current = ""
            for token in tokens:
                if not current:
                    current = token
                elif len(current) + len(token) <= max_chars:
                    current += token
                else:
                    chunks.append(current)
                    current = token
            if current:
                chunks.append(current)
            return chunks
        return [text]

    safe_limit = max(4, max_chars)
    return _split_preserving_marks(text, safe_limit)


def _split_preserving_marks(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in text:
        if current and len(current) >= limit and not _is_combining_mark(char):
            chunks.append(current)
            current = char
        else:
            current += char
    if current:
        chunks.append(current)
    return chunks


def _is_combining_mark(char: str) -> bool:
    return unicodedata.category(char).startswith("M") or "\u0E31" <= char <= "\u0E4E"


def _truncate_text(text: str, max_width_units: float) -> str:
    ellipsis = "..."
    if _text_width_units(text) <= max_width_units:
        return text
    limit = max(1.0, max_width_units - _text_width_units(ellipsis))
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width_units(candidate) > limit and not _is_combining_mark(char):
            break
        current = candidate
    return current.rstrip() + ellipsis
