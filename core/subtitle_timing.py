from __future__ import annotations

import re

from core.subtitle_layout import wrap_subtitle_text
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo


def estimate_display_duration(
    text: str,
    *,
    video_info: VideoInfo,
    style: SubtitleStyle,
    min_duration: float = 1.0,
    max_duration: float = 6.0,
) -> float:
    """Estimate a readable subtitle duration from text length and rendered wrapping."""
    visible_text = re.sub(r"\s+", "", text)
    char_count = max(1, len(visible_text))
    wrapped_lines = wrap_subtitle_text(text, video_info, style)
    line_count = max(1, len(wrapped_lines))

    # Slightly slower for small/vertical layouts because each line carries fewer words.
    chars_per_second = 13.0
    if video_info.orientation == "portrait":
        chars_per_second = 11.5
    elif video_info.orientation == "square":
        chars_per_second = 12.0

    duration = (char_count / chars_per_second) + (line_count * 0.18)
    return max(min_duration, min(max_duration, duration))


def cleanup_subtitle_timings(
    cues: list[SubtitleCue],
    *,
    video_info: VideoInfo,
    style: SubtitleStyle,
    silences: list[tuple[float, float | None]] | None = None,
    hold_after_sentence: float = 0.35,
    min_duration: float = 0.9,
    max_duration: float = 6.0,
    min_gap_before_next: float = 0.08,
) -> list[SubtitleCue]:
    """Trim subtitles that stay on screen too long after the likely spoken phrase.

    This does not run speech recognition. It uses the imported cue start/end, the next cue
    start, and a reading-duration estimate based on the current video/style.
    """
    if not cues:
        return []

    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    cleaned: list[SubtitleCue] = []
    for idx, cue in enumerate(ordered):
        next_start = ordered[idx + 1].start if idx + 1 < len(ordered) else video_info.duration
        original_duration = cue.end - cue.start
        readable_duration = estimate_display_duration(
            cue.text,
            video_info=video_info,
            style=style,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        target_duration = min(original_duration, readable_duration + hold_after_sentence)
        target_duration = max(min_duration, target_duration)

        end = cue.start + target_duration
        silence_end = _silence_start_inside_cue(cue, silences or [])
        if silence_end is not None:
            end = min(end, max(cue.start + min_duration, silence_end + hold_after_sentence))
        if next_start and next_start > cue.start:
            end = min(end, max(cue.start + min_duration, next_start - min_gap_before_next))
        if video_info.duration > 0:
            end = min(end, video_info.duration)
        if end <= cue.start:
            end = min(cue.start + min_duration, video_info.duration or cue.start + min_duration)

        cleaned.append(SubtitleCue(idx + 1, cue.start, end, cue.text))
    return cleaned


def _silence_start_inside_cue(
    cue: SubtitleCue, silences: list[tuple[float, float | None]]
) -> float | None:
    for silence_start, silence_end in silences:
        if silence_end is not None and silence_end <= cue.start:
            continue
        if cue.start < silence_start <= cue.end:
            return silence_start
    return None
