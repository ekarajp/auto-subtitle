from __future__ import annotations

from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo


def refine_subtitle_timings(
    cues: list[SubtitleCue],
    *,
    video_info: VideoInfo,
    min_duration: float,
    max_duration: float,
    hold_after_sentence: float,
    min_gap: float = 0.04,
) -> list[SubtitleCue]:
    if not cues:
        return []

    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    refined: list[SubtitleCue] = []
    max_end = video_info.duration if video_info.duration > 0 else None
    cursor = 0.0

    for index, cue in enumerate(ordered):
        start = max(0.0, cue.start)
        if refined:
            start = max(start, cursor)
        end = max(cue.end + hold_after_sentence, start + min_duration)
        end = min(end, start + max_duration)
        if index + 1 < len(ordered):
            next_start = max(start + min_duration, ordered[index + 1].start)
            end = min(end, max(start + min_duration, next_start - min_gap))
        if max_end is not None:
            end = min(end, max_end)
        if end <= start:
            end = start + min_duration
            if max_end is not None:
                end = min(end, max_end)
        if end <= start:
            continue
        refined.append(
            SubtitleCue(
                len(refined) + 1,
                start,
                end,
                cue.text,
                style_overrides=dict(cue.style_overrides),
            )
        )
        cursor = end + min_gap
    return refined
