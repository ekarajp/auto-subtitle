from __future__ import annotations

from core.subtitle_models import SubtitleCue
from core.text_normalizer import compact_text_identity, normalize_source_text, visible_character_count
from core.thai_text_processor import natural_text_chunks


def has_authoritative_source_text(cues: list[SubtitleCue] | None) -> bool:
    return bool(cues and any(normalize_source_text(cue.text) for cue in cues))


def prepare_source_cues(
    cues: list[SubtitleCue],
    *,
    split_long_text: bool,
    max_chars_per_chunk: int,
) -> list[SubtitleCue]:
    """Prepare source text for sync while preserving wording and order."""
    prepared: list[SubtitleCue] = []
    for cue in cues:
        text = normalize_source_text(cue.text)
        if not text:
            continue
        chunks = [text]
        if split_long_text and visible_character_count(text) > max_chars_per_chunk * 1.4:
            chunks = natural_text_chunks(text, max_chars=max_chars_per_chunk)
        for chunk in chunks:
            prepared.append(
                SubtitleCue(
                    len(prepared) + 1,
                    max(0.0, cue.start),
                    max(cue.start + 0.05, cue.end),
                    chunk,
                    style_overrides=dict(cue.style_overrides),
                )
            )
    return prepared


def source_identity(cues: list[SubtitleCue]) -> str:
    return "".join(compact_text_identity(cue.text) for cue in cues)
