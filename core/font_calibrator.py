from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.font_calibration import (
    FontCalibrationProfile,
    detect_script_category,
    resolve_font_calibration,
    save_font_calibration_profiles,
    temporary_profile_overrides,
)
from core.font_utils import font_supports_text
from core.preview_renderer import render_accurate_preview_frame
from core.renderer import ensure_ffmpeg
from core.style_preset import SubtitleStyle
from core.subtitle_layout import style_calibration_key
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo
from ui.preview_widget import VideoSubtitleCanvas


@dataclass(slots=True)
class CalibrationSample:
    text: str
    width: int
    height: int
    duration: float = 2.0


@dataclass(slots=True)
class CalibrationResult:
    family: str
    script: str
    style_key: str
    best_profile: FontCalibrationProfile
    score: float
    sample_count: int


DEFAULT_SAMPLES: tuple[CalibrationSample, ...] = (
    CalibrationSample("Hamburgefons AVMWyqgp\n1234567890 !?.,", 1280, 720),
    CalibrationSample("\u0e2a\u0e34\u0e48\u0e07\u0e21\u0e35\u0e0a\u0e35\u0e27\u0e34\u0e15\u0e17\u0e38\u0e01\u0e0a\u0e19\u0e34\u0e14\n\u0e2d\u0e2d\u0e01\u0e41\u0e1a\u0e1a\u0e21\u0e32", 1080, 1920),
    CalibrationSample("\u6f22\u5b57\u3068\u3072\u3089\u304c\u306a\n\u30ab\u30bf\u30ab\u30ca 123", 1080, 1080),
    CalibrationSample("\u0627\u0644\u0639\u0631\u0628\u064a\u0629 \u0648\u0627\u0644\u0646\u0635\n12345 \u061f !", 1280, 720),
    CalibrationSample("\u0939\u093f\u0928\u094d\u0926\u0940 \u0926\u0947\u0935\u0928\u093e\u0917\u0930\u0940\n12345", 1280, 720),
)


def auto_calibrate_font_profile(
    family: str,
    *,
    script: str | None = None,
    sample_texts: list[CalibrationSample] | None = None,
    base_style: SubtitleStyle | None = None,
    save_result: bool = False,
) -> CalibrationResult:
    app = QApplication.instance() or QApplication([])
    del app
    samples = sample_texts or list(DEFAULT_SAMPLES)
    if script:
        samples = [sample for sample in samples if detect_script_category(sample.text) == script]
    relevant_samples = [sample for sample in samples if _sample_relevant_to_family(sample, family)]
    if not relevant_samples:
        relevant_samples = list(samples)
    if not relevant_samples:
        raise ValueError(f"No calibration samples available for script {script!r}.")

    style_key = style_calibration_key(base_style or SubtitleStyle())
    detected_script = detect_script_category(relevant_samples[0].text)
    default_profile = resolve_font_calibration(family, relevant_samples[0].text, style_key)
    best_profile = FontCalibrationProfile.from_dict(default_profile.to_dict())
    best_profile.family = family
    best_profile.script = detected_script
    best_profile.style_key = style_key
    base_score = _profile_score(family, best_profile, relevant_samples, base_style)
    best_score = base_score
    estimated = _estimate_profile_from_bboxes(family, best_profile, relevant_samples, base_style)
    candidates = _refinement_candidates(best_profile, estimated)

    for candidate in candidates:
        score = _profile_score(family, candidate, relevant_samples, base_style)
        if score < best_score:
            best_score = score
            best_profile = candidate

    if save_result:
        save_font_calibration_profiles([best_profile])
    return CalibrationResult(
        family=family,
        script=detected_script,
        style_key=style_key,
        best_profile=best_profile,
        score=best_score,
        sample_count=len(relevant_samples),
    )


def auto_calibrate_font_profiles(
    family: str,
    *,
    scripts: list[str] | None = None,
    sample_texts: list[CalibrationSample] | None = None,
    base_style: SubtitleStyle | None = None,
    save_result: bool = False,
) -> list[CalibrationResult]:
    requested_scripts = scripts or sorted({detect_script_category(sample.text) for sample in (sample_texts or list(DEFAULT_SAMPLES))})
    results: list[CalibrationResult] = []
    for script in requested_scripts:
        try:
            results.append(
                auto_calibrate_font_profile(
                    family,
                    script=script,
                    sample_texts=sample_texts,
                    base_style=base_style,
                    save_result=False,
                )
            )
        except ValueError:
            continue
    if save_result:
        save_font_calibration_profiles([result.best_profile for result in results])
    return results


def _profile_score(
    family: str,
    profile: FontCalibrationProfile,
    samples: list[CalibrationSample],
    base_style: SubtitleStyle | None,
) -> float:
    total = 0.0
    for sample in samples:
        preview_bbox, accurate_bbox = _render_bboxes(
            family,
            sample,
            profile,
            base_style=base_style,
        )
        preview_center = ((preview_bbox[0] + preview_bbox[2]) / 2.0, (preview_bbox[1] + preview_bbox[3]) / 2.0)
        accurate_center = ((accurate_bbox[0] + accurate_bbox[2]) / 2.0, (accurate_bbox[1] + accurate_bbox[3]) / 2.0)
        total += abs(preview_center[0] - accurate_center[0]) * 8.0
        total += abs(preview_center[1] - accurate_center[1]) * 8.0
        total += abs((preview_bbox[2] - preview_bbox[0]) - (accurate_bbox[2] - accurate_bbox[0]))
        total += abs((preview_bbox[3] - preview_bbox[1]) - (accurate_bbox[3] - accurate_bbox[1]))
    return total / max(1, len(samples))


def _estimate_profile_from_bboxes(
    family: str,
    profile: FontCalibrationProfile,
    samples: list[CalibrationSample],
    base_style: SubtitleStyle | None,
) -> FontCalibrationProfile:
    size_scales: list[float] = []
    path_scale_ys: list[float] = []
    baselines: list[float] = []
    style = base_style or SubtitleStyle()
    ass_size = max(1.0, style.font_size * 2.05 * max(0.05, profile.size_scale))
    for sample in samples:
        preview_bbox, accurate_bbox = _render_bboxes(family, sample, profile, base_style=base_style)
        preview_width = max(1, preview_bbox[2] - preview_bbox[0])
        preview_height = max(1, preview_bbox[3] - preview_bbox[1])
        accurate_width = max(1, accurate_bbox[2] - accurate_bbox[0])
        accurate_height = max(1, accurate_bbox[3] - accurate_bbox[1])
        width_ratio = accurate_width / preview_width
        estimated_size = profile.size_scale * width_ratio
        predicted_height = preview_height * width_ratio
        height_ratio_after_size = accurate_height / max(1.0, predicted_height)
        preview_center_y = (preview_bbox[1] + preview_bbox[3]) / 2.0
        accurate_center_y = (accurate_bbox[1] + accurate_bbox[3]) / 2.0
        center_delta_y = preview_center_y - accurate_center_y
        size_scales.append(_clamp(estimated_size, 0.20, 1.20))
        path_scale_ys.append(_clamp(profile.path_scale_y * height_ratio_after_size, 0.70, 1.80))
        baselines.append(_clamp(profile.baseline_offset - (center_delta_y / ass_size), -0.20, 0.20))

    estimated = FontCalibrationProfile.from_dict(profile.to_dict())
    if size_scales:
        estimated.size_scale = round(_median(size_scales), 4)
    if path_scale_ys:
        estimated.path_scale_y = round(_median(path_scale_ys), 4)
    if baselines:
        estimated.baseline_offset = round(_median(baselines), 4)
    return estimated


def _refinement_candidates(
    base: FontCalibrationProfile,
    estimated: FontCalibrationProfile,
) -> list[FontCalibrationProfile]:
    candidates: list[FontCalibrationProfile] = []
    for size_delta in (-0.02, 0.0, 0.02):
        for path_y_delta in (-0.05, 0.0, 0.05):
            for baseline_delta in (-0.01, 0.0, 0.01):
                candidate = FontCalibrationProfile.from_dict(estimated.to_dict())
                candidate.size_scale = round(_clamp(estimated.size_scale + size_delta, 0.20, 1.20), 4)
                candidate.path_scale_y = round(_clamp(estimated.path_scale_y + path_y_delta, 0.70, 1.80), 4)
                candidate.baseline_offset = round(_clamp(estimated.baseline_offset + baseline_delta, -0.20, 0.20), 4)
                candidates.append(candidate)
    candidates.append(base)
    return candidates


def _render_bboxes(
    family: str,
    sample: CalibrationSample,
    profile: FontCalibrationProfile,
    *,
    base_style: SubtitleStyle | None,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    ffmpeg = ensure_ffmpeg()
    style = SubtitleStyle.from_dict((base_style or SubtitleStyle()).to_dict())
    style.font_family = family
    style.font_size = 48
    style.stroke_enabled = True
    style.stroke_width = 3.0
    style.shadow_enabled = True
    style.shadow_offset = 2.0
    style.alignment = "bottom_center"
    cue = SubtitleCue(1, 0.0, sample.duration, sample.text)
    with tempfile.TemporaryDirectory(prefix="smart_subtitle_calibrate_") as temp_dir:
        blank_path = Path(temp_dir) / "blank.mp4"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=#242A31:s={sample.width}x{sample.height}:d={sample.duration}",
                "-pix_fmt",
                "yuv420p",
                str(blank_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        info = VideoInfo(blank_path, sample.width, sample.height, sample.duration, 25.0, "h264")
        with temporary_profile_overrides([profile]):
            accurate_image = QImage.fromData(
                render_accurate_preview_frame(
                    video_info=info,
                    cues=[cue],
                    style=style,
                    position_seconds=min(0.5, sample.duration - 0.01),
                )
            )
            preview_bbox = _render_preview_bbox(info, cue, style)
            accurate_bbox = _bbox(accurate_image)
    return preview_bbox, accurate_bbox


def _render_preview_bbox(info: VideoInfo, cue: SubtitleCue, style: SubtitleStyle) -> tuple[int, int, int, int]:
    canvas = VideoSubtitleCanvas()
    canvas.resize(info.width, info.height)
    canvas.set_video_info(info)
    canvas.set_style(style)
    canvas.set_cues([cue])
    image = QImage(info.width, info.height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#242A31"))
    painter = QPainter(image)
    canvas._draw_subtitle(painter, canvas._video_rect(), cue)
    painter.end()
    return _bbox(image)


def _bbox(image: QImage) -> tuple[int, int, int, int]:
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    background = np.array([0x31, 0x2A, 0x24, 0xFF], dtype=np.uint8)
    arr = np.frombuffer(image.bits(), np.uint8).reshape((image.height(), image.width(), 4))
    diff = np.any(np.abs(arr.astype(np.int16) - background.astype(np.int16)) > 20, axis=2)
    ys, xs = np.where(diff)
    if len(xs) == 0:
        raise RuntimeError("Calibration render produced no subtitle pixels.")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _sample_relevant_to_family(sample: CalibrationSample, family: str) -> bool:
    return font_supports_text(family, sample.text)


def _around(center: float, span: float, step: float) -> list[float]:
    values: list[float] = []
    current = center - span
    while current <= center + span + 1e-9:
        values.append(round(current, 4))
        current += step
    return values


def _unique_values(values: list[float]) -> list[float]:
    seen: set[float] = set()
    unique: list[float] = []
    for value in values:
        rounded = round(value, 4)
        if rounded in seen:
            continue
        seen.add(rounded)
        unique.append(rounded)
    return unique


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
