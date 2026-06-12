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

SAFE_AREA_MODE_LABELS: dict[str, str] = {
    "auto": "Auto",
    "shorts": "YouTube Shorts",
    "reels": "Instagram Reels",
    "tiktok": "TikTok",
    "all": "All Platforms",
    "landscape": "Landscape",
    "portrait": "Portrait",
    "custom": "Custom",
}
SAFE_AREA_MODES = tuple(SAFE_AREA_MODE_LABELS)


@dataclass(frozen=True, slots=True)
class SafeAreaInsets:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def horizontal(self) -> int:
        return self.left + self.right

    @property
    def vertical(self) -> int:
        return self.top + self.bottom


_SAFE_AREA_PERCENT_PRESETS: dict[str, tuple[float, float, float, float]] = {
    # left, top, right, bottom. Vertical short-form platforms have asymmetric
    # UI chrome: captions/actions sit mostly on the right and bottom. These
    # presets are tuned for subtitle placement, not full ad/key-visual safety
    # templates, so they avoid over-compressing readable captions.
    "landscape": (6.0, 7.0, 6.0, 7.0),
    "portrait": (6.0, 10.0, 6.0, 10.0),
    "shorts": (6.0, 10.0, 10.0, 18.0),
    "reels": (6.0, 14.0, 8.0, 20.0),
    "tiktok": (6.0, 10.0, 12.0, 20.0),
    "all": (6.0, 14.0, 12.0, 20.0),
}


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
    "Shorts": SubtitleStyle(font_family="Arial", font_size=54, stroke_width=3.5, max_width_percent=88, safe_area_mode="shorts"),
    "Reels": SubtitleStyle(font_size=54, stroke_width=3.5, max_width_percent=86, safe_area_mode="reels"),
    "TikTok": SubtitleStyle(
        font_size=58,
        stroke_width=4.0,
        background_enabled=True,
        background_opacity=35,
        max_width_percent=84,
        safe_area_mode="tiktok",
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
    return safe_area_insets(video_info, style).bottom


def effective_bottom_margin(video_info: VideoInfo, style: SubtitleStyle) -> int:
    if style.bottom_margin > 0:
        return style.bottom_margin
    return auto_bottom_margin(video_info, style)


def auto_horizontal_margin(video_info: VideoInfo, style: SubtitleStyle) -> int:
    insets = safe_area_insets(video_info, style)
    return max(insets.left, insets.right)


def effective_horizontal_margin(video_info: VideoInfo, style: SubtitleStyle) -> int:
    if style.horizontal_margin > 0:
        return style.horizontal_margin
    return auto_horizontal_margin(video_info, style)


def safe_area_insets(video_info: VideoInfo, style: SubtitleStyle) -> SafeAreaInsets:
    mode = normalized_safe_area_mode(style.safe_area_mode, video_info)
    if mode == "custom":
        percent = max(1, min(30, style.custom_safe_area_percent))
        left_pct = top_pct = right_pct = bottom_pct = float(percent)
    else:
        left_pct, top_pct, right_pct, bottom_pct = _SAFE_AREA_PERCENT_PRESETS[mode]

    return SafeAreaInsets(
        left=max(16, round(video_info.width * left_pct / 100)),
        top=max(18, round(video_info.height * top_pct / 100)),
        right=max(16, round(video_info.width * right_pct / 100)),
        bottom=max(18, round(video_info.height * bottom_pct / 100)),
    )


def effective_safe_area_insets(video_info: VideoInfo, style: SubtitleStyle) -> SafeAreaInsets:
    insets = safe_area_insets(video_info, style)
    horizontal = style.horizontal_margin if style.horizontal_margin > 0 else None
    vertical = style.bottom_margin if style.bottom_margin > 0 else None
    return SafeAreaInsets(
        left=max(16, horizontal) if horizontal is not None else insets.left,
        top=max(18, vertical) if vertical is not None else insets.top,
        right=max(16, horizontal) if horizontal is not None else insets.right,
        bottom=max(18, vertical) if vertical is not None else insets.bottom,
    )


def normalized_safe_area_mode(mode: str, video_info: VideoInfo) -> str:
    if mode == "auto":
        if video_info.orientation == "portrait":
            return "portrait"
        if video_info.orientation == "landscape":
            return "landscape"
        return "portrait"
    if mode in _SAFE_AREA_PERCENT_PRESETS or mode == "custom":
        return mode
    return "all"


def safe_area_label(mode: str) -> str:
    return SAFE_AREA_MODE_LABELS.get(mode, mode.title())
