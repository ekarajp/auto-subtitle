from __future__ import annotations

from core.speech_types import SpeechWord
from core.source_text_handler import prepare_source_cues, source_identity
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.text_normalizer import visible_character_count
from core.timing_refiner import refine_subtitle_timings
from core.video_info import VideoInfo


def align_source_cues_to_speech(
    source_cues: list[SubtitleCue],
    words: list[SpeechWord],
    video_info: VideoInfo,
    style: SubtitleStyle,
    *,
    min_duration: float,
    max_duration: float,
    hold_after_sentence: float,
    max_chars_per_line: int,
    max_lines: int,
    preserve_source_text: bool = True,
) -> list[SubtitleCue]:
    """Align authoritative subtitle text to speech timestamps.

    Whisper words are used as a timing ruler only. The displayed text comes from
    source_cues, which prevents clean user text from being replaced by noisy ASR.
    """
    del preserve_source_text
    if not source_cues:
        return []
    prepared = prepare_source_cues(
        source_cues,
        split_long_text=True,
        max_chars_per_chunk=max(12, max_chars_per_line * max(1, max_lines)),
    )
    if not prepared:
        return []
    if not words:
        return _spread_source_cues_over_video(
            prepared,
            video_info,
            min_duration=min_duration,
            max_duration=max_duration,
        )
    if len(prepared) > len(words):
        return _spread_source_cues_over_range(
            prepared,
            words[0].start,
            words[-1].end,
            video_info,
            min_duration=min_duration,
            max_duration=max_duration,
            hold_after_sentence=hold_after_sentence,
        )

    cue_weights = [max(1, visible_character_count(cue.text)) for cue in prepared]
    total_weight = max(1, sum(cue_weights))
    word_count = len(words)
    aligned: list[SubtitleCue] = []
    previous_end_index = 0
    cumulative = 0

    for index, (cue, weight) in enumerate(zip(prepared, cue_weights)):
        cumulative += weight
        start_index = previous_end_index
        if index == len(prepared) - 1:
            end_index = word_count
        else:
            target_end = round((cumulative / total_weight) * word_count)
            min_end = start_index + 1
            remaining_cues = len(prepared) - index - 1
            max_end = max(min_end, word_count - remaining_cues)
            end_index = max(min_end, min(max_end, target_end))
        segment_words = words[start_index:end_index] or [words[min(start_index, word_count - 1)]]
        start = segment_words[0].start
        end = segment_words[-1].end
        aligned.append(
            SubtitleCue(
                len(aligned) + 1,
                start,
                max(end, start + min_duration),
                cue.text,
                style_overrides=dict(cue.style_overrides),
            )
        )
        previous_end_index = end_index

    refined = refine_subtitle_timings(
        aligned,
        video_info=video_info,
        min_duration=min_duration,
        max_duration=max_duration,
        hold_after_sentence=hold_after_sentence,
    )
    if source_identity(refined) != source_identity(prepared):
        return _spread_source_cues_over_range(
            prepared,
            words[0].start,
            words[-1].end,
            video_info,
            min_duration=min_duration,
            max_duration=max_duration,
            hold_after_sentence=hold_after_sentence,
        )
    style.max_lines = max(1, max_lines)
    return refined


def _spread_source_cues_over_video(
    cues: list[SubtitleCue],
    video_info: VideoInfo,
    *,
    min_duration: float,
    max_duration: float,
) -> list[SubtitleCue]:
    duration = video_info.duration if video_info.duration > 0 else sum(max(1, visible_character_count(cue.text) / 13) for cue in cues)
    weights = [max(1, visible_character_count(cue.text)) for cue in cues]
    total = max(1, sum(weights))
    cursor = 0.0
    aligned: list[SubtitleCue] = []
    for cue, weight in zip(cues, weights):
        cue_duration = max(min_duration, min(max_duration, duration * (weight / total)))
        end = min(duration, cursor + cue_duration)
        if end <= cursor:
            end = cursor + min_duration
        aligned.append(SubtitleCue(len(aligned) + 1, cursor, end, cue.text, style_overrides=dict(cue.style_overrides)))
        cursor = end + 0.04
    return aligned


def _spread_source_cues_over_range(
    cues: list[SubtitleCue],
    start_time: float,
    end_time: float,
    video_info: VideoInfo,
    *,
    min_duration: float,
    max_duration: float,
    hold_after_sentence: float,
) -> list[SubtitleCue]:
    duration = max(min_duration * len(cues), end_time - start_time)
    weights = [max(1, visible_character_count(cue.text)) for cue in cues]
    total = max(1, sum(weights))
    cursor = max(0.0, start_time)
    aligned: list[SubtitleCue] = []
    for cue, weight in zip(cues, weights):
        cue_duration = max(min_duration, min(max_duration, duration * (weight / total)))
        aligned.append(
            SubtitleCue(
                len(aligned) + 1,
                cursor,
                cursor + cue_duration,
                cue.text,
                style_overrides=dict(cue.style_overrides),
            )
        )
        cursor += cue_duration + 0.04
    return refine_subtitle_timings(
        aligned,
        video_info=video_info,
        min_duration=min_duration,
        max_duration=max_duration,
        hold_after_sentence=hold_after_sentence,
    )
