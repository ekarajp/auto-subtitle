from __future__ import annotations

from dataclasses import asdict, dataclass

from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from core.font_calibration import calibration_debug_summary
from core.font_utils import resolve_font_details
from core.style_preset import SubtitleStyle
from core.subtitle_layout import (
    preview_baseline_shift,
    preview_font_scale,
    preview_font_stretch,
    preview_font_vertical_nudge,
    preview_font_x_offset,
    preview_line_height_scale,
    style_calibration_key,
    style_for_ass_export,
    style_for_preview,
)


@dataclass(slots=True)
class FontMeasurementDiagnostics:
    requested_family: str
    resolved_family: str
    fallback_used: bool
    script: str
    ass_font_size: int
    preview_font_size: int
    preview_stretch: int
    baseline_shift: int
    vertical_nudge: int
    horizontal_nudge: int
    line_height_scale: float
    ascent: int
    descent: int
    leading: int
    line_spacing: int
    style_key: str
    calibration: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def collect_font_measurement_diagnostics(style: SubtitleStyle, sample_text: str) -> FontMeasurementDiagnostics:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication must exist before collecting font diagnostics.")

    resolution = resolve_font_details(style.font_family, sample_text)
    resolved_family = resolution.resolved_family
    preview_style = style_for_preview(style, sample_text)
    ass_style = style_for_ass_export(style)
    preview_font = QFont(preview_style.font_family)
    preview_font.setPixelSize(preview_style.font_size)
    preview_font.setStretch(preview_font_stretch(style, sample_text))
    metrics = QFontMetrics(preview_font)
    key = style_calibration_key(style)
    calibration = calibration_debug_summary(resolved_family, sample_text, key)
    return FontMeasurementDiagnostics(
        requested_family=style.font_family,
        resolved_family=resolved_family,
        fallback_used=resolution.fallback_used,
        script=str(calibration["script"]),
        ass_font_size=ass_style.font_size,
        preview_font_size=preview_style.font_size,
        preview_stretch=preview_font.stretch(),
        baseline_shift=preview_baseline_shift(preview_style.font_size, style, sample_text),
        vertical_nudge=preview_font_vertical_nudge(style, sample_text, preview_style.font_size),
        horizontal_nudge=preview_font_x_offset(style, sample_text, preview_style.font_size),
        line_height_scale=preview_line_height_scale(style, sample_text),
        ascent=metrics.ascent(),
        descent=metrics.descent(),
        leading=metrics.leading(),
        line_spacing=metrics.lineSpacing(),
        style_key=key,
        calibration=calibration,
    )
