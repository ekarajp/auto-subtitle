from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from core.ass_builder import wrap_subtitle_text
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo


class SpeechSyncError(RuntimeError):
    """Raised when optional speech-to-text sync cannot run."""


@dataclass(slots=True)
class SpeechWord:
    text: str
    start: float
    end: float


@dataclass(slots=True)
class SpeechSyncOptions:
    model_size: str = "small"
    language: str | None = None
    compute_type: str = "auto"
    beam_size: int = 5
    best_of: int = 5
    pause_threshold: float = 0.45
    hold_after_sentence: float = 0.25
    min_duration: float = 0.55
    max_duration: float = 4.5
    max_words_per_cue: int = 12
    target_chars_per_second: float = 15.0


ProgressCallback = Callable[[int, str], None]


def transcribe_video_to_cues(
    video_info: VideoInfo,
    style: SubtitleStyle,
    *,
    options: SpeechSyncOptions,
    progress_callback: ProgressCallback | None = None,
) -> list[SubtitleCue]:
    """Transcribe the video audio and build subtitle cues from word timestamps.

    This feature is optional. It requires `faster-whisper`, but the main app does
    not import that package unless the user explicitly starts speech sync.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SpeechSyncError(
            "Speech Sync requires the optional package faster-whisper. "
            "Install it with: pip install faster-whisper"
        ) from exc

    _emit(progress_callback, 2, f"Loading Whisper model: {options.model_size}")
    try:
        model = WhisperModel(
            options.model_size,
            device="auto",
            compute_type="default" if options.compute_type == "auto" else options.compute_type,
        )
    except Exception as exc:
        raise SpeechSyncError(f"Cannot load Whisper model '{options.model_size}': {exc}") from exc

    _emit(progress_callback, 8, "Transcribing video audio with word timestamps...")
    try:
        segments, info = model.transcribe(
            str(Path(video_info.path)),
            language=options.language or None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=max(1, options.beam_size),
            best_of=max(1, options.best_of),
            temperature=0.0,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            vad_parameters={"min_silence_duration_ms": round(options.pause_threshold * 1000)},
        )
    except Exception as exc:
        raise SpeechSyncError(f"Whisper transcription failed: {exc}") from exc

    language_label = getattr(info, "language", None) or options.language or "auto"
    _emit(progress_callback, 12, f"Detected language: {language_label}")
    words = _collect_words(segments, video_info.duration, progress_callback)
    if not words:
        raise SpeechSyncError("No speech words were detected in the video audio.")

    _emit(progress_callback, 86, "Building subtitle cues from speech timing...")
    cues = build_cues_from_words(words, video_info, style, options=options)
    if not cues:
        raise SpeechSyncError("Speech was detected, but no subtitle cues could be built.")
    _emit(progress_callback, 100, f"Speech Sync generated {len(cues)} subtitle cue(s).")
    return cues


def build_cues_from_words(
    words: list[SpeechWord],
    video_info: VideoInfo,
    style: SubtitleStyle,
    *,
    options: SpeechSyncOptions,
) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    current: list[SpeechWord] = []
    max_lines = max(1, style.max_lines)

    for word in words:
        if not word.text:
            continue
        if current:
            gap = max(0.0, word.start - current[-1].end)
            candidate_text = _join_words([*current, word])
            candidate_lines = wrap_subtitle_text(candidate_text, video_info, style, limit_lines=False)
            duration = max(0.0, word.end - current[0].start)
            current_text = _join_words(current)
            should_split_before = (
                _is_strong_pause(gap, current)
                or len(candidate_lines) > max_lines
                or _is_too_dense(candidate_text, duration, options)
                or (duration > options.max_duration and _can_split(current))
                or (len(current) >= options.max_words_per_cue and _can_split(current))
                or (_soft_sentence_boundary(current_text) and duration >= options.min_duration and gap >= 0.12)
            )
            if should_split_before:
                _append_cue(cues, current, options=options, video_duration=video_info.duration)
                current = []

        current.append(word)
        text = _join_words(current)
        duration = max(0.0, current[-1].end - current[0].start)
        if _sentence_ends(text) and duration >= options.min_duration:
            _append_cue(cues, current, options=options, video_duration=video_info.duration)
            current = []

    if current:
        _append_cue(cues, current, options=options, video_duration=video_info.duration)

    return _avoid_overlaps(cues)


def _collect_words(
    segments: Iterable[object],
    duration: float,
    progress_callback: ProgressCallback | None,
) -> list[SpeechWord]:
    words: list[SpeechWord] = []
    for segment in segments:
        segment_end = float(getattr(segment, "end", 0.0) or 0.0)
        if duration > 0:
            percent = 12 + round(min(1.0, segment_end / duration) * 72)
            _emit(progress_callback, percent, "")

        segment_words = getattr(segment, "words", None) or []
        if segment_words:
            for item in segment_words:
                text = _clean_word(str(getattr(item, "word", "") or ""))
                if not text:
                    continue
                start = float(getattr(item, "start", getattr(segment, "start", 0.0)) or 0.0)
                end = float(getattr(item, "end", getattr(segment, "end", start + 0.1)) or start + 0.1)
                words.append(SpeechWord(text=text, start=max(0.0, start), end=max(start + 0.05, end)))
            continue

        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = float(getattr(segment, "end", start + 0.1) or start + 0.1)
        words.append(SpeechWord(text=text, start=max(0.0, start), end=max(start + 0.05, end)))
    return words


def _append_cue(
    cues: list[SubtitleCue],
    words: list[SpeechWord],
    *,
    options: SpeechSyncOptions,
    video_duration: float,
) -> None:
    text = _join_words(words).strip()
    if not text:
        return
    start = max(0.0, words[0].start)
    spoken_end = words[-1].end
    end = max(spoken_end + options.hold_after_sentence, start + options.min_duration)
    end = min(end, start + options.max_duration)
    if video_duration > 0:
        end = min(video_duration, end)
    if end <= start:
        end = start + options.min_duration
    cues.append(SubtitleCue(len(cues) + 1, start, end, text))


def _avoid_overlaps(cues: list[SubtitleCue], *, gap: float = 0.04) -> list[SubtitleCue]:
    fixed: list[SubtitleCue] = []
    for index, cue in enumerate(cues):
        end = cue.end
        if index + 1 < len(cues):
            next_start = cues[index + 1].start
            end = min(end, max(cue.start + 0.1, next_start - gap))
        fixed.append(SubtitleCue(len(fixed) + 1, cue.start, end, cue.text))
    return fixed


def _join_words(words: list[SpeechWord]) -> str:
    text = ""
    for word in words:
        if not text:
            text = word.text
        elif _contains_thai(text[-1]) and _contains_thai(word.text[0]):
            text += word.text
        elif _is_punctuation(word.text):
            text += word.text
        else:
            text += " " + word.text
    return re.sub(r"\s+", " ", text).strip()


def _is_strong_pause(gap: float, current: list[SpeechWord]) -> bool:
    if gap >= 0.85:
        return True
    if gap >= 0.45 and _can_split(current):
        return True
    return gap >= 0.28 and _soft_sentence_boundary(_join_words(current)) and _can_split(current)


def _can_split(words: list[SpeechWord]) -> bool:
    text = re.sub(r"\s+", "", _join_words(words))
    return len(words) >= 2 and len(text) >= 6


def _soft_sentence_boundary(text: str) -> bool:
    stripped = text.strip()
    if _sentence_ends(stripped):
        return True
    return bool(re.search(r"[,;:，、]|(ครับ|ค่ะ|คะ|นะ|เลย|แล้ว|ด้วย|มาก|จริง)$", stripped))


def _is_too_dense(text: str, duration: float, options: SpeechSyncOptions) -> bool:
    if duration <= 0:
        return False
    visible_chars = len(re.sub(r"\s+", "", text))
    return visible_chars / duration > options.target_chars_per_second * 1.35


def _clean_word(text: str) -> str:
    return text.strip().replace("\n", " ")


def _contains_thai(text: str) -> bool:
    return any("\u0e00" <= char <= "\u0e7f" for char in text)


def _is_punctuation(text: str) -> bool:
    return bool(re.fullmatch(r"[.,!?;:，。！？]+", text))


def _sentence_ends(text: str) -> bool:
    return bool(re.search(r"[.!?。！？]$", text.strip()))


def _emit(callback: ProgressCallback | None, percent: int, message: str) -> None:
    if callback:
        callback(max(0, min(100, percent)), message)
