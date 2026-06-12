from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue


@dataclass(slots=True)
class ProjectConfig:
    video_path: str = ""
    subtitle_path: str = ""
    subtitle_format: str = "auto"
    txt_mode: str = "auto"
    txt_fixed_duration: float = 3.0
    hold_after_sentence: float = 0.35
    min_display_duration: float = 0.9
    max_display_duration: float = 6.0
    use_silence_detection: bool = True
    output_path: str = ""
    style: SubtitleStyle = field(default_factory=SubtitleStyle)
    subtitle_cues: list[SubtitleCue] = field(default_factory=list)
    subtitle_source_format: str = "unknown"
    selected_row: int = 0
    playhead_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["style"] = self.style.to_dict()
        payload["subtitle_cues"] = [cue_to_dict(cue) for cue in self.subtitle_cues]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ProjectConfig":
        style_payload = payload.get("style", {})
        style = (
            SubtitleStyle.from_dict(style_payload)
            if isinstance(style_payload, dict)
            else SubtitleStyle()
        )
        return cls(
            video_path=str(payload.get("video_path", "")),
            subtitle_path=str(payload.get("subtitle_path", "")),
            subtitle_format=str(payload.get("subtitle_format", "auto")),
            txt_mode=str(payload.get("txt_mode", "auto")),
            txt_fixed_duration=float(payload.get("txt_fixed_duration", 3.0)),
            hold_after_sentence=float(payload.get("hold_after_sentence", 0.35)),
            min_display_duration=float(payload.get("min_display_duration", 0.9)),
            max_display_duration=float(payload.get("max_display_duration", 6.0)),
            use_silence_detection=bool(payload.get("use_silence_detection", True)),
            output_path=str(payload.get("output_path", "")),
            style=style,
            subtitle_cues=cues_from_payload(payload.get("subtitle_cues", [])),
            subtitle_source_format=str(payload.get("subtitle_source_format", "unknown")),
            selected_row=int(payload.get("selected_row", 0)),
            playhead_ms=max(0, int(payload.get("playhead_ms", 0))),
        )


def save_project_config(path: str | Path, config: ProjectConfig) -> None:
    target = Path(path)
    target.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_project_config(path: str | Path) -> ProjectConfig:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Project config ต้องเป็น JSON object")
    return ProjectConfig.from_dict(payload)


def cue_to_dict(cue: SubtitleCue) -> dict[str, object]:
    return {
        "index": cue.index,
        "start": cue.start,
        "end": cue.end,
        "text": cue.text,
        "style_overrides": dict(cue.style_overrides),
    }


def cues_from_payload(payload: object) -> list[SubtitleCue]:
    if not isinstance(payload, list):
        return []
    cues: list[SubtitleCue] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        cues.append(
            SubtitleCue(
                int(item.get("index", index)),
                float(item.get("start", 0.0)),
                float(item.get("end", 0.0)),
                str(item.get("text", "")),
                style_overrides=dict(item.get("style_overrides", {}) or {}),
            )
        )
    return cues
