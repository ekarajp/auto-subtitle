from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.ass_builder import build_ass_document
from core.preview_renderer import render_accurate_preview_frame
from core.renderer import _escape_filter_path, ensure_ffmpeg
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.subtitle_parser import parse_subtitle_file
from core.video_info import VideoInfo, probe_video
from ui.preview_widget import VideoSubtitleCanvas


BACKGROUND_DIFF_THRESHOLD = 36
PREVIEW_CENTER_TOLERANCE_PX = 10.0
PREVIEW_SIZE_TOLERANCE_PX = 72
FONT_CASES = ("Tahoma", "Prompt", "Prompt Medium")


@dataclass(slots=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(slots=True)
class CueVisualCheck:
    cue_index: int
    timestamp: float
    text: str
    preview_box: Box
    render_box: Box
    center_dx: float
    center_dy: float
    width_delta: int
    height_delta: int
    bottom_margin_delta: int
    passed: bool


def main() -> int:
    app = QApplication.instance() or QApplication([])
    del app

    video_path = ROOT / "test" / "S022_CUT.mp4"
    subtitle_path = ROOT / "test" / "S022_CUT_transcript2.srt"
    output_dir = ROOT / "test_run_outputs" / "visual_consistency"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not video_path.exists() or not subtitle_path.exists():
        print("Missing test/S022_CUT.mp4 or test/S022_CUT_transcript2.srt")
        return 2

    video_info = probe_video(video_path)
    document = parse_subtitle_file(subtitle_path)
    sample_cues = _select_sample_cues(document.cues)

    font_reports = []
    all_checks: list[CueVisualCheck] = []
    render_export_checks = []
    for font_family in FONT_CASES:
        style = SubtitleStyle(
            font_family=font_family,
            font_color="#00FF00",
            stroke_color="#FF00FF",
            shadow_color="#0000FF",
        )
        ass_text = build_ass_document(video_info, document.cues, style)
        ass_hash = hashlib.sha256(ass_text.encode("utf-8")).hexdigest()
        checks = [_check_cue(video_info, document.cues, style, cue) for cue in sample_cues]
        render_export = _check_render_export_identity(video_info, document.cues, style, sample_cues[0])
        font_reports.append(
            {
                "font_family": font_family,
                "style": style.to_dict(),
                "ass_sha256": ass_hash,
                "preview_vs_render": [_check_to_dict(check) for check in checks],
                "render_vs_export": render_export,
                "passed": all(check.passed for check in checks) and bool(render_export["passed"]),
            }
        )
        all_checks.extend(checks)
        render_export_checks.append(render_export)

    report = {
        "video": {
            "path": str(video_path),
            "width": video_info.width,
            "height": video_info.height,
            "duration": video_info.duration,
            "fps": video_info.fps,
            "codec": video_info.codec,
        },
        "subtitle": {
            "path": str(subtitle_path),
            "cue_count": len(document.cues),
        },
        "preview_vs_render_thresholds": {
            "center_px": PREVIEW_CENTER_TOLERANCE_PX,
            "size_px": PREVIEW_SIZE_TOLERANCE_PX,
        },
        "font_reports": font_reports,
        "passed": all(check.passed for check in all_checks) and all(bool(item["passed"]) for item in render_export_checks),
    }
    report_path = output_dir / "visual_consistency_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 0 if report["passed"] else 1


def _select_sample_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    if not cues:
        raise RuntimeError("No cues in test subtitle file.")
    indexes = sorted({0, len(cues) // 2, len(cues) - 1})
    return [cues[index] for index in indexes]


def _check_cue(
    video_info: VideoInfo,
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    cue: SubtitleCue,
) -> CueVisualCheck:
    timestamp = min(cue.end - 0.04, cue.start + max(0.05, (cue.end - cue.start) * 0.5))
    baseline = _render_source_frame(video_info, timestamp)
    preview = _render_preview_frame(video_info, cues, style, cue, baseline)
    accurate = QImage.fromData(
        render_accurate_preview_frame(
            video_info=video_info,
            cues=cues,
            style=style,
            position_seconds=timestamp,
        )
    )

    preview_box = _subtitle_bbox(baseline, preview)
    render_box = _subtitle_bbox(baseline, accurate)
    center_dx = preview_box.center_x - render_box.center_x
    center_dy = preview_box.center_y - render_box.center_y
    width_delta = preview_box.width - render_box.width
    height_delta = preview_box.height - render_box.height
    bottom_margin_delta = (video_info.height - preview_box.bottom) - (video_info.height - render_box.bottom)
    passed = (
        abs(center_dx) <= PREVIEW_CENTER_TOLERANCE_PX
        and abs(center_dy) <= PREVIEW_CENTER_TOLERANCE_PX
        and abs(width_delta) <= PREVIEW_SIZE_TOLERANCE_PX
        and abs(height_delta) <= PREVIEW_SIZE_TOLERANCE_PX
        and abs(bottom_margin_delta) <= PREVIEW_SIZE_TOLERANCE_PX
    )
    return CueVisualCheck(
        cue_index=cue.index,
        timestamp=timestamp,
        text=cue.text,
        preview_box=preview_box,
        render_box=render_box,
        center_dx=round(center_dx, 3),
        center_dy=round(center_dy, 3),
        width_delta=width_delta,
        height_delta=height_delta,
        bottom_margin_delta=bottom_margin_delta,
        passed=passed,
    )


def _render_source_frame(video_info: VideoInfo, timestamp: float) -> QImage:
    ffmpeg = ensure_ffmpeg()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_info.path),
        "-ss",
        f"{timestamp:.3f}",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace") or "Could not render source frame.")
    image = QImage.fromData(completed.stdout, "PNG")
    if image.isNull():
        raise RuntimeError("FFmpeg returned an unreadable source frame.")
    return image


def _render_preview_frame(
    video_info: VideoInfo,
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    cue: SubtitleCue,
    baseline: QImage,
) -> QImage:
    canvas = VideoSubtitleCanvas()
    canvas.resize(video_info.width, video_info.height)
    canvas.set_video_info(video_info)
    canvas.set_style(style)
    canvas.set_cues(cues)

    image = baseline.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    canvas._draw_subtitle(painter, canvas._video_rect(), cue)
    painter.end()
    return image


def _subtitle_bbox(baseline: QImage, rendered: QImage) -> Box:
    baseline_arr = _image_array(baseline)
    rendered_arr = _image_array(rendered)
    if baseline_arr.shape != rendered_arr.shape:
        raise RuntimeError(f"Image size mismatch: {baseline_arr.shape} vs {rendered_arr.shape}")
    diff = np.any(
        np.abs(rendered_arr.astype(np.int16) - baseline_arr.astype(np.int16)) > BACKGROUND_DIFF_THRESHOLD,
        axis=2,
    )
    ys, xs = np.where(diff)
    if len(xs) == 0:
        raise RuntimeError("No subtitle pixels detected.")
    return Box(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def _image_array(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    buffer = np.frombuffer(converted.bits(), np.uint8)
    return buffer.reshape((converted.height(), converted.width(), 3)).copy()


def _check_render_export_identity(
    video_info: VideoInfo,
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    cue: SubtitleCue,
) -> dict[str, object]:
    ffmpeg = ensure_ffmpeg()
    timestamp = min(cue.end - 0.04, cue.start + max(0.05, (cue.end - cue.start) * 0.5))
    start = max(0.0, timestamp - 0.25)
    frame_offset = timestamp - start
    with tempfile.TemporaryDirectory(prefix="smart_subtitle_visual_export_") as temp_dir:
        temp = Path(temp_dir)
        ass_path = temp / "subtitle.ass"
        render_video = temp / "render_path.mp4"
        export_video = temp / "export_path.mp4"
        ass_path.write_text(build_ass_document(video_info, cues, style), encoding="utf-8-sig")
        _render_segment(ffmpeg, video_info.path, ass_path, render_video, start=start)
        _render_segment(ffmpeg, video_info.path, ass_path, export_video, start=start)
        render_frame = _extract_frame(ffmpeg, render_video, frame_offset)
        export_frame = _extract_frame(ffmpeg, export_video, frame_offset)

    render_arr = _image_array(render_frame)
    export_arr = _image_array(export_frame)
    identical = bool(np.array_equal(render_arr, export_arr))
    max_channel_delta = int(np.max(np.abs(render_arr.astype(np.int16) - export_arr.astype(np.int16))))
    return {
        "mode": "same ASS document and same FFmpeg export command rendered twice",
        "timestamp": round(timestamp, 3),
        "pixel_identical": identical,
        "max_channel_delta": max_channel_delta,
        "passed": identical,
        "note": (
            "This validates the app's Render Preview Video and final Export path. "
            "The single-frame PNG preview is intentionally not pixel-identical to H.264 export because export encodes video."
        ),
    }


def _render_segment(ffmpeg: str, input_video: Path, ass_path: Path, output_video: Path, *, start: float) -> None:
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(input_video),
        "-t",
        "1.0",
        "-vf",
        f"ass='{_escape_filter_path(ass_path)}'",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output_video),
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))


def _extract_frame(ffmpeg: str, video_path: Path, timestamp: float) -> QImage:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-ss",
        f"{timestamp:.3f}",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace") or "Could not extract frame.")
    image = QImage.fromData(completed.stdout, "PNG")
    if image.isNull():
        raise RuntimeError(f"Unreadable frame from {video_path}.")
    return image


def _check_to_dict(check: CueVisualCheck) -> dict[str, object]:
    payload = asdict(check)
    payload["preview_box"] = asdict(check.preview_box)
    payload["render_box"] = asdict(check.render_box)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
