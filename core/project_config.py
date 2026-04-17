from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.style_preset import SubtitleStyle


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

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["style"] = self.style.to_dict()
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
