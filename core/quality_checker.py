from __future__ import annotations

import re

from core.subtitle_layout import wrap_subtitle_text
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.text_normalizer import compact_text_identity, visible_character_count
from core.thai_text_processor import likely_broken_thai_fragment
from core.video_info import VideoInfo


def check_subtitle_quality(
    cues: list[SubtitleCue],
    *,
    video_info: VideoInfo,
    style: SubtitleStyle,
    source_identity: str | None = None,
    min_duration: float = 0.75,
    max_chars_per_second: float = 18.0,
) -> list[str]:
    notes: list[str] = []
    if source_identity is not None:
        output_identity = "".join(compact_text_identity(cue.text) for cue in cues)
        if output_identity != source_identity:
            notes.append("Source text changed during sync. Review required.")

    for cue in cues:
        duration = max(0.001, cue.end - cue.start)
        compact_len = visible_character_count(cue.text)
        if duration < min_duration:
            notes.append(f"Cue {cue.index}: duration is very short ({duration:.2f}s).")
        if compact_len / duration > max_chars_per_second:
            notes.append(f"Cue {cue.index}: reading speed is high ({compact_len / duration:.1f} chars/sec).")
        if likely_broken_thai_fragment(cue.text):
            notes.append(f"Cue {cue.index}: possible broken Thai fragment.")
        if _looks_like_garbage(cue.text):
            notes.append(f"Cue {cue.index}: suspicious repeated/noisy text.")
        lines = wrap_subtitle_text(cue.text, video_info, style, limit_lines=False)
        if len(lines) > max(1, style.max_lines):
            notes.append(f"Cue {cue.index}: wraps to {len(lines)} lines; max is {style.max_lines}.")
    return notes


def _looks_like_garbage(text: str) -> bool:
    stripped = re.sub(r"\s+", "", text or "")
    if not stripped:
        return True
    if re.search(r"(.)\1{8,}", stripped):
        return True
    punctuation_ratio = sum(1 for char in stripped if not char.isalnum() and not ("\u0E00" <= char <= "\u0E7F")) / max(1, len(stripped))
    return punctuation_ratio > 0.45
