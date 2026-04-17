from __future__ import annotations

import re

from core.style_preset import SubtitleStyle, style_with_overrides
from core.subtitle_layout import (
    ASS_FONT_SCALE,
    style_for_ass_export as shared_style_for_ass_export,
    subtitle_line_height,
    subtitle_line_positions as shared_subtitle_line_positions,
    subtitle_max_width,
    wrap_subtitle_text as shared_wrap_subtitle_text,
)
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo
from utils.timecode import format_ass_time


ASS_EXPORT_FONT_SCALE = ASS_FONT_SCALE


def build_ass_document(video_info: VideoInfo, cues: list[SubtitleCue], style: SubtitleStyle) -> str:
    """Build an ASS subtitle document ready for FFmpeg's ass filter."""
    header = _build_header(video_info, style_for_ass_export(style))
    events = [_build_event_lines(video_info, cue, style) for cue in cues]
    return header + "\n".join(line for group in events for line in group) + "\n"


def style_for_ass_export(style: SubtitleStyle) -> SubtitleStyle:
    """Return the calibrated style used by FFmpeg/libass export."""
    return shared_style_for_ass_export(style)


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
    ass_style = style_for_ass_export(wrap_style)
    start = format_ass_time(cue.start)
    end = format_ass_time(cue.end)
    lines = shared_wrap_subtitle_text(cue.text, video_info, wrap_style, limit_lines=False)
    positions = shared_subtitle_line_positions(video_info, ass_style, len(lines), renderer="ass")
    blur_tag = f"\\blur{ass_style.shadow_blur:.1f}" if ass_style.shadow_blur > 0 else ""

    result: list[str] = []
    if ass_style.background_enabled:
        result.append(_build_background_box_event(video_info, start, end, ass_style, positions, len(lines)))
    for line, (x, y, an) in zip(lines, positions):
        override = f"{{\\an{an}\\pos({x},{y}){blur_tag}}}"
        result.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{override}{escape_ass_text(line)}")
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

    line_height = subtitle_line_height(style)
    max_width = subtitle_max_width(video_info, style)
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


def subtitle_line_positions(
    video_info: VideoInfo, style: SubtitleStyle, line_count: int
) -> list[tuple[int, int, int]]:
    return shared_subtitle_line_positions(video_info, style, line_count, renderer="preview")


def wrap_subtitle_text(
    text: str,
    video_info: VideoInfo,
    style: SubtitleStyle,
    *,
    limit_lines: bool = True,
) -> list[str]:
    return shared_wrap_subtitle_text(text, video_info, style, limit_lines=limit_lines)


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
