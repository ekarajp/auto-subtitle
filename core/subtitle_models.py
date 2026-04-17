from __future__ import annotations

from dataclasses import dataclass, field

from utils.timecode import format_timecode


class SubtitleParseError(ValueError):
    """Raised when a subtitle file cannot be parsed."""


@dataclass(slots=True)
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str
    style_overrides: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.text = self.text.strip()
        if self.start < 0:
            raise SubtitleParseError(f"Cue {self.index}: start time cannot be negative.")
        if self.end <= self.start:
            raise SubtitleParseError(
                f"Cue {self.index}: end time must be greater than start time."
            )
        if not self.text:
            raise SubtitleParseError(f"Cue {self.index}: text is empty.")
        self.style_overrides = dict(self.style_overrides or {})

    @property
    def start_label(self) -> str:
        return format_timecode(self.start)

    @property
    def end_label(self) -> str:
        return format_timecode(self.end)


@dataclass(slots=True)
class SubtitleDocument:
    cues: list[SubtitleCue] = field(default_factory=list)
    source_format: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.cues)

    def validate_against_duration(self, duration: float | None) -> list[str]:
        warnings = list(self.warnings)
        if duration is None or duration <= 0:
            return warnings
        for cue in self.cues:
            if cue.start > duration:
                warnings.append(
                    f"Cue {cue.index} starts after video duration ({cue.start_label})."
                )
            elif cue.end > duration:
                warnings.append(
                    f"Cue {cue.index} ends after video duration ({cue.end_label}); it will be clipped by the video end."
                )
        return warnings
