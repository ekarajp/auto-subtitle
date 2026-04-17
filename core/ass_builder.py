from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from core.style_preset import (
    SubtitleStyle,
    effective_bottom_margin,
    effective_horizontal_margin,
    style_with_overrides,
)
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo
from utils.timecode import format_ass_time


ASS_EXPORT_FONT_SCALE = 1.33


def build_ass_document(video_info: VideoInfo, cues: list[SubtitleCue], style: SubtitleStyle) -> str:
    """Build an ASS subtitle document ready for FFmpeg's ass filter."""
    header = _build_header(video_info, _style_for_ass_export(style))
    events = [_build_event_lines(video_info, cue, style) for cue in cues]
    return header + "\n".join(line for group in events for line in group) + "\n"


def _style_for_ass_export(style: SubtitleStyle) -> SubtitleStyle:
    """ASS Fontsize renders smaller than Qt preview point sizes on Windows.

    The app exposes one font-size control to users, so export is scaled here to
    visually match the real-time preview instead of asking users to compensate.
    """
    copied = SubtitleStyle.from_dict(style.to_dict())
    copied.font_size = max(1, round(copied.font_size * ASS_EXPORT_FONT_SCALE))
    copied.line_spacing = round(copied.line_spacing * ASS_EXPORT_FONT_SCALE)
    return copied


def _build_header(video_info: VideoInfo, style: SubtitleStyle) -> str:
    border_style = 1
    outline = max(0.0, style.stroke_width) if style.stroke_enabled else 0.0
    shadow = max(0.0, style.shadow_offset) if style.shadow_enabled else 0
    back_color = (
        ass_color(style.background_color, opacity_percent=style.background_opacity)
        if style.background_enabled
        else ass_color(style.shadow_color, opacity_percent=100)
    )

    return (
        "[Script Info]\n"
        "Title: Smart Subtitle Export\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_info.width}\n"
        f"PlayResY: {video_info.height}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,"
        f"{_escape_commas(style.font_family)},"
        f"{style.font_size},"
        f"{ass_color(style.font_color, opacity_percent=100)},"
        f"{ass_color(style.font_color, opacity_percent=100)},"
        f"{ass_color(style.stroke_color, opacity_percent=100)},"
        f"{back_color},"
        f"0,0,0,0,100,100,0,0,{border_style},{outline:.1f},{shadow:.1f},5,20,20,20,1\n"
        "Style: Box,Arial,1,"
        f"{ass_color(style.background_color, opacity_percent=style.background_opacity)},"
        f"{ass_color(style.background_color, opacity_percent=style.background_opacity)},"
        f"{ass_color(style.background_color, opacity_percent=style.background_opacity)},"
        f"{ass_color(style.background_color, opacity_percent=style.background_opacity)},"
        "0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _build_event_lines(video_info: VideoInfo, cue: SubtitleCue, style: SubtitleStyle) -> list[str]:
    wrap_style = style_with_overrides(style, cue.style_overrides)
    style = _style_for_ass_export(wrap_style)
    start = format_ass_time(cue.start)
    end = format_ass_time(cue.end)
    lines = wrap_subtitle_text(cue.text, video_info, wrap_style, limit_lines=False)
    positions = _line_positions(video_info, style, len(lines))
    blur_tag = f"\\blur{style.shadow_blur:.1f}" if style.shadow_blur > 0 else ""

    result: list[str] = []
    if style.background_enabled:
        result.append(_build_background_box_event(video_info, start, end, style, positions, len(lines)))
    for line, (x, y, an) in zip(lines, positions):
        override = f"{{\\an{an}\\pos({x},{y}){blur_tag}}}"
        text = override + escape_ass_text(line)
        result.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{text}")
    return result


def _build_background_box_event(
    video_info: VideoInfo,
    start: str,
    end: str,
    style: SubtitleStyle,
    positions: list[tuple[int, int, int]],
    line_count: int,
) -> str:
    if not positions:
        return f"Dialogue: 0,{start},{end},Box,,0,0,0,,"

    line_height = max(1, round(style.font_size * 1.18 + style.line_spacing))
    max_width = round(video_info.width * max(20, min(style.max_width_percent, 100)) / 100)
    pad_x = max(16, round(style.font_size * 0.45))
    pad_y = max(8, round(style.font_size * 0.24))

    first_x, first_y, an = positions[0]
    last_y = positions[min(len(positions), line_count) - 1][1]
    top = round(first_y - line_height / 2 - pad_y)
    bottom = round(last_y + line_height / 2 + pad_y)

    if an == 4:
        left = round(first_x - pad_x)
        right = round(first_x + max_width + pad_x)
    elif an == 6:
        left = round(first_x - max_width - pad_x)
        right = round(first_x + pad_x)
    else:
        left = round(first_x - max_width / 2 - pad_x)
        right = round(first_x + max_width / 2 + pad_x)

    left = max(0, min(video_info.width, left))
    right = max(0, min(video_info.width, right))
    top = max(0, min(video_info.height, top))
    bottom = max(0, min(video_info.height, bottom))

    path = f"m {left} {top} l {right} {top} l {right} {bottom} l {left} {bottom}"
    return f"Dialogue: 0,{start},{end},Box,,0,0,0,,{{\\an7\\pos(0,0)\\p1}}{path}"


def _line_positions(
    video_info: VideoInfo, style: SubtitleStyle, line_count: int
) -> list[tuple[int, int, int]]:
    line_count = max(1, line_count)
    margin = effective_bottom_margin(video_info, style)
    safe_x = effective_horizontal_margin(video_info, style)
    line_height = max(1, round(style.font_size * 1.18 + style.line_spacing))

    if style.text_position == "custom":
        base_x = round(video_info.width * style.custom_x_percent / 100)
        base_y = round(video_info.height * style.custom_y_percent / 100)
        y_start = base_y - round((line_count - 1) * line_height / 2)
    else:
        if style.alignment == "top_center":
            y_start = margin
        elif style.alignment == "center":
            y_start = round(video_info.height / 2 - ((line_count - 1) * line_height / 2))
        else:
            y_start = video_info.height - margin - ((line_count - 1) * line_height)

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

    positions = []
    for idx in range(line_count):
        y = max(8, min(video_info.height - 8, y_start + (idx * line_height)))
        x = max(8, min(video_info.width - 8, base_x))
        positions.append((round(x), round(y), ass_alignment))
    return positions


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

    max_width_px = video_info.width * max(20, min(style.max_width_percent, 100)) / 100
    visual_font_px = max(1.0, style.font_size * ASS_EXPORT_FONT_SCALE)
    max_width_units = max(4.0, max_width_px / visual_font_px)

    wrapped: list[str] = []
    for source in source_lines:
        wrapped.extend(_wrap_one_line(source, max_width_units, style.max_lines))

    max_lines = max(1, style.max_lines)
    if limit_lines and len(wrapped) > max_lines:
        kept = wrapped[:max_lines]
        kept[-1] = _truncate_text(kept[-1], max_width_units)
        return kept
    return wrapped


def _wrap_one_line(text: str, max_width_units: float, max_lines: int) -> list[str]:
    del max_lines
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
        else:
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

    # Fallback keeps common Thai phrase chunks together better than fixed character slicing.
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
    return "\u0E31" <= first <= "\u0E4E"


def _looks_like_split_thai_tail(token: str) -> bool:
    # Spacing vowels such as ะ, า, แ are valid Thai characters, but if a token starts
    # with one after another Thai token it is usually a bad split, e.g. "ร" + "ะหว่าง".
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


def escape_ass_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return escaped.replace("\n", "\\N")


def ass_color(hex_color: str, *, opacity_percent: int = 100) -> str:
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", cleaned):
        cleaned = "FFFFFF"
    rr = cleaned[0:2]
    gg = cleaned[2:4]
    bb = cleaned[4:6]
    opacity = max(0, min(100, opacity_percent))
    alpha = round(255 * (100 - opacity) / 100)
    return f"&H{alpha:02X}{bb}{gg}{rr}"


def _escape_commas(value: str) -> str:
    return value.replace(",", " ")
