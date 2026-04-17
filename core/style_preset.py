from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from core.video_info import VideoInfo


ALIGNMENTS = {
    "bottom_center": "Bottom Center",
    "bottom_left": "Bottom Left",
    "bottom_right": "Bottom Right",
    "center": "Center",
    "top_center": "Top Center",
}

SAFE_AREA_MODES = ("auto", "landscape", "portrait", "custom")


@dataclass(slots=True)
class SubtitleStyle:
    font_family: str = "Tahoma"
    font_size: int = 48
    font_color: str = "#FFFFFF"
    stroke_enabled: bool = True
    stroke_color: str = "#000000"
    stroke_width: float = 3.0
    shadow_enabled: bool = True
    shadow_color: str = "#000000"
    shadow_offset: float = 2.0
    shadow_blur: float = 0.0
    background_enabled: bool = False
    background_color: str = "#000000"
    background_opacity: int = 55
    alignment: str = "bottom_center"
    bottom_margin: int = 0
    horizontal_margin: int = 0
    safe_area_mode: str = "auto"
    custom_safe_area_percent: int = 8
    line_spacing: int = 4
    max_width_percent: int = 88
    max_lines: int = 2
    text_position: str = "auto"
    custom_x_percent: int = 50
    custom_y_percent: int = 84

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SubtitleStyle":
        allowed = {field.name for field in fields(cls)}
        filtered = {key: value for key, value in payload.items() if key in allowed}
        return cls(**filtered)


STYLE_PRESETS: dict[str, SubtitleStyle] = {
    "Clean": SubtitleStyle(max_width_percent=88, stroke_width=2.5),
    "YouTube": SubtitleStyle(font_family="Arial", font_size=50, stroke_width=3.5, max_width_percent=90),
    "TikTok": SubtitleStyle(
        font_size=58,
        stroke_width=4.0,
        background_enabled=True,
        background_opacity=35,
        max_width_percent=84,
        custom_y_percent=78,
    ),
    "Documentary": SubtitleStyle(
        font_family="Georgia",
        font_size=44,
        font_color="#F4F4F4",
        stroke_width=2.0,
        shadow_enabled=False,
        background_enabled=True,
        background_opacity=45,
        max_width_percent=86,
    ),
}


def style_with_auto_size(style: SubtitleStyle, video_info: VideoInfo) -> SubtitleStyle:
    copied = SubtitleStyle.from_dict(style.to_dict())
    base = min(video_info.width, video_info.height)
    if video_info.orientation == "portrait":
        copied.font_size = max(34, round(base * 0.055))
    elif video_info.orientation == "square":
        copied.font_size = max(34, round(base * 0.052))
    else:
        copied.font_size = max(32, round(video_info.height * 0.055))
    copied.bottom_margin = auto_bottom_margin(video_info, copied)
    return copied


def style_with_overrides(style: SubtitleStyle, overrides: dict[str, object] | None) -> SubtitleStyle:
    copied = SubtitleStyle.from_dict(style.to_dict())
    if not overrides:
        return copied

    allowed = {field.name for field in fields(SubtitleStyle)}
    payload = copied.to_dict()
    for key, value in overrides.items():
        if key in allowed:
            payload[key] = value
    return SubtitleStyle.from_dict(payload)


def auto_bottom_margin(video_info: VideoInfo, style: SubtitleStyle) -> int:
    mode = style.safe_area_mode
    height = video_info.height
    if mode == "custom":
        percent = style.custom_safe_area_percent
    elif mode == "portrait" or (mode == "auto" and video_info.orientation == "portrait"):
        percent = 10
    elif mode == "landscape" or (mode == "auto" and video_info.orientation == "landscape"):
        percent = 7
    else:
        percent = 8
    return max(18, round(height * percent / 100))


def effective_bottom_margin(video_info: VideoInfo, style: SubtitleStyle) -> int:
    if style.bottom_margin > 0:
        return style.bottom_margin
    return auto_bottom_margin(video_info, style)


def auto_horizontal_margin(video_info: VideoInfo, style: SubtitleStyle) -> int:
    del style
    return max(16, round(video_info.width * 0.06))


def effective_horizontal_margin(video_info: VideoInfo, style: SubtitleStyle) -> int:
    if style.horizontal_margin > 0:
        return style.horizontal_margin
    return auto_horizontal_margin(video_info, style)
