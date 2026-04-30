from __future__ import annotations

from core.subtitle_layout import wrap_subtitle_text
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.text_normalizer import normalize_source_text, visible_character_count
from core.thai_text_processor import natural_text_chunks
from core.video_info import VideoInfo


def arrange_cues_for_readability(
    cues: list[SubtitleCue],
    *,
    video_info: VideoInfo,
    style: SubtitleStyle,
    max_lines: int = 2,
    min_duration: float = 0.75,
    gap: float = 0.04,
) -> list[SubtitleCue]:
    """Split long cues into shorter readable cues that fit the current layout."""
    if not cues:
        return []

    arranged: list[SubtitleCue] = []
    max_lines = max(1, max_lines)
    working_style = SubtitleStyle.from_dict(style.to_dict())
    working_style.max_lines = max_lines

    for cue in sorted(cues, key=lambda item: (item.start, item.end)):
        chunks = _readable_chunks(cue.text, video_info=video_info, style=working_style, max_lines=max_lines)
        if len(chunks) <= 1:
            arranged.append(
                SubtitleCue(
                    len(arranged) + 1,
                    cue.start,
                    cue.end,
                    "\n".join(chunks[0] if chunks else [normalize_source_text(cue.text)]),
                    style_overrides=dict(cue.style_overrides),
                )
            )
            continue

        duration = max(0.01, cue.end - cue.start)
        usable_duration = max(0.01, duration - (gap * (len(chunks) - 1)))
        weights = [max(1, len("".join(chunk))) for chunk in chunks]
        total_weight = sum(weights)
        durations = [usable_duration * (weight / total_weight) for weight in weights]
        if usable_duration / len(chunks) >= min_duration:
            durations = [max(min_duration, value) for value in durations]
            total_duration = sum(durations)
            if total_duration > usable_duration:
                scale = usable_duration / total_duration
                durations = [max(0.05, value * scale) for value in durations]

        cursor = cue.start
        for index, (chunk, chunk_duration) in enumerate(zip(chunks, durations)):
            if index == len(chunks) - 1:
                end = cue.end
            else:
                end = min(cue.end, cursor + chunk_duration)
            text = "\n".join(chunk)
            if end <= cursor:
                end = cursor + max(0.05, chunk_duration)
            arranged.append(
                SubtitleCue(
                    len(arranged) + 1,
                    cursor,
                    end,
                    text,
                    style_overrides=dict(cue.style_overrides),
                )
            )
            cursor = min(cue.end, end + gap)

    return _avoid_overlaps(arranged, min_gap=gap)


def _readable_chunks(
    text: str,
    *,
    video_info: VideoInfo,
    style: SubtitleStyle,
    max_lines: int,
) -> list[list[str]]:
    cleaned = " ".join(normalize_source_text(text).splitlines()).strip()
    if not cleaned:
        return []

    target_chars = _target_chars_per_line(video_info, style) * max(1, max_lines)
    phrase_chunks = natural_text_chunks(cleaned, max_chars=target_chars)
    chunks: list[list[str]] = []
    for phrase in phrase_chunks or [cleaned]:
        lines = wrap_subtitle_text(phrase, video_info, style, limit_lines=False)
        chunks.extend(_chunk_lines(lines, max_lines))
    return _merge_short_orphan_chunks(chunks, video_info=video_info, style=style, max_lines=max_lines)


def _chunk_lines(lines: list[str], max_lines: int) -> list[list[str]]:
    if not lines:
        return []
    return [lines[index : index + max_lines] for index in range(0, len(lines), max_lines)]


def _merge_short_orphan_chunks(
    chunks: list[list[str]],
    *,
    video_info: VideoInfo,
    style: SubtitleStyle,
    max_lines: int,
) -> list[list[str]]:
    if len(chunks) < 2:
        return chunks

    merged: list[list[str]] = []
    for chunk in chunks:
        if (
            merged
            and visible_character_count("\n".join(chunk)) <= 8
            and _can_merge_chunks(merged[-1], chunk, video_info=video_info, style=style, max_lines=max_lines)
        ):
            text = f"{' '.join(merged[-1])} {' '.join(chunk)}".strip()
            merged[-1] = wrap_subtitle_text(text, video_info, style, limit_lines=False)
        else:
            merged.append(chunk)
    return merged


def _can_merge_chunks(
    left: list[str],
    right: list[str],
    *,
    video_info: VideoInfo,
    style: SubtitleStyle,
    max_lines: int,
) -> bool:
    text = f"{' '.join(left)} {' '.join(right)}".strip()
    return len(wrap_subtitle_text(text, video_info, style, limit_lines=False)) <= max_lines


def _target_chars_per_line(video_info: VideoInfo, style: SubtitleStyle) -> int:
    if video_info.orientation == "portrait":
        base = 34
    elif video_info.orientation == "square":
        base = 38
    else:
        base = 42
    width_scale = max(0.45, min(1.15, style.max_width_percent / 88.0))
    font_scale = max(0.65, min(1.35, 48.0 / max(1, style.font_size)))
    return max(12, round(base * width_scale * font_scale))


def _avoid_overlaps(cues: list[SubtitleCue], *, min_gap: float) -> list[SubtitleCue]:
    fixed: list[SubtitleCue] = []
    for index, cue in enumerate(cues):
        next_start = cues[index + 1].start if index + 1 < len(cues) else None
        end = cue.end
        if next_start is not None and end > next_start - min_gap:
            end = max(cue.start + 0.1, next_start - min_gap)
        fixed.append(
            SubtitleCue(
                len(fixed) + 1,
                cue.start,
                end,
                cue.text,
                style_overrides=dict(cue.style_overrides),
            )
        )
    return fixed
