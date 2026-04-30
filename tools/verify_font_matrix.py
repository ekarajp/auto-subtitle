from __future__ import annotations

import argparse
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

from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.ass_builder import build_ass_document
from core.preview_renderer import render_accurate_preview_frame
from core.renderer import _escape_filter_path, ensure_ffmpeg
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo
from ui.preview_widget import VideoSubtitleCanvas


BG_HEX = "#242A31"
BG_RGB = np.array([0x24, 0x2A, 0x31], dtype=np.uint8)
DIFF_THRESHOLD = 28
DEFAULT_CENTER_TOLERANCE = 10.0
DEFAULT_SIZE_TOLERANCE = 52
DEFAULT_FONTS = (
    "Tahoma",
    "Arial",
    "Segoe UI",
    "Noto Sans Thai",
    "Leelawadee UI",
    "Prompt",
    "Prompt Medium",
    "Prompt SemiBold",
    "Prompt Black",
    "Angsana New",
    "Cordia New",
)
SCRIPT_TEXTS = {
    "thai": "\u0e17\u0e14\u0e2a\u0e2d\u0e1a\u0e1f\u0e2d\u0e19\u0e15\u0e4c\u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22\n\u0e02\u0e19\u0e32\u0e14\u0e41\u0e25\u0e30\u0e23\u0e30\u0e22\u0e30\u0e15\u0e49\u0e2d\u0e07\u0e15\u0e23\u0e07",
    "latin": "Preview and render must match\nSize position spacing",
    "mixed": "\u0e17\u0e14\u0e2a\u0e2d\u0e1a Prompt Medium 123\nPreview \u0e01\u0e31\u0e1a render \u0e15\u0e49\u0e2d\u0e07\u0e15\u0e23\u0e07",
}


@dataclass(slots=True)
class FontMatrixCheck:
    font_family: str
    script: str
    style_name: str
    font_size: int
    preview_box: dict[str, int]
    render_box: dict[str, int]
    center_dx: float
    center_dy: float
    width_delta: int
    height_delta: int
    passed: bool
    error: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Qt preview text against FFmpeg/libass across fonts.")
    parser.add_argument("--fonts", nargs="*", default=list(DEFAULT_FONTS), help="Font families to test, or 'all'.")
    parser.add_argument("--sizes", nargs="*", type=int, default=[32, 48, 72], help="Source font sizes to test.")
    parser.add_argument("--scripts", nargs="*", default=["thai", "latin", "mixed"], choices=sorted(SCRIPT_TEXTS))
    parser.add_argument(
        "--styles",
        nargs="*",
        default=["default", "no-stroke", "heavy-stroke", "background"],
        choices=["default", "no-stroke", "heavy-stroke", "background", "top", "left", "right", "tight-lines"],
    )
    parser.add_argument("--max-fonts", type=int, default=0, help="Limit font count after filtering. 0 means no limit.")
    parser.add_argument("--max-checks", type=int, default=0, help="Limit total preview/render checks. 0 means no limit.")
    parser.add_argument("--export-checks", type=int, default=3, help="Number of render/export identity checks to run.")
    parser.add_argument("--center-tolerance", type=float, default=DEFAULT_CENTER_TOLERANCE)
    parser.add_argument("--size-tolerance", type=int, default=DEFAULT_SIZE_TOLERANCE)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    del app

    output_dir = ROOT / "test_run_outputs" / "font_matrix"
    output_dir.mkdir(parents=True, exist_ok=True)
    fonts = _selected_fonts(args.fonts, args.max_fonts)
    ffmpeg = ensure_ffmpeg()

    with tempfile.TemporaryDirectory(prefix="smart_subtitle_font_matrix_") as temp_dir:
        temp = Path(temp_dir)
        video = _make_blank_video(ffmpeg, temp)
        video_info = VideoInfo(video, 960, 540, 2.0, 25.0, "h264")
        baseline = _blank_image(video_info.width, video_info.height)

        checks: list[FontMatrixCheck] = []
        export_reports: list[dict[str, object]] = []
        stopped_by_limit = False
        for font_family in fonts:
            for script in args.scripts:
                cue = SubtitleCue(1, 0.0, 1.5, SCRIPT_TEXTS[script])
                for size in args.sizes:
                    for style_name in args.styles:
                        if args.max_checks and len(checks) >= args.max_checks:
                            stopped_by_limit = True
                            break
                        style = _style_for_case(font_family, size, style_name)
                        try:
                            checks.append(
                                _check_case(
                                    video_info,
                                    baseline,
                                    cue,
                                    style,
                                    script,
                                    style_name,
                                    center_tolerance=args.center_tolerance,
                                    size_tolerance=args.size_tolerance,
                                )
                            )
                        except Exception as exc:
                            checks.append(
                                _failed_check(
                                    style,
                                    script,
                                    style_name,
                                    error=str(exc),
                                )
                            )
                    if stopped_by_limit:
                        break
                if stopped_by_limit:
                    break
            if stopped_by_limit:
                break

        for check in checks[: max(0, args.export_checks)]:
            style = _style_for_case(check.font_family, check.font_size, check.style_name)
            cue = SubtitleCue(1, 0.0, 1.5, SCRIPT_TEXTS[check.script])
            export_reports.append(_check_render_export_identity(ffmpeg, video_info, cue, style, temp))

    failures = [check for check in checks if not check.passed]
    report = {
        "font_count": len(fonts),
        "checked_count": len(checks),
        "stopped_by_limit": stopped_by_limit,
        "thresholds": {
            "center_px": args.center_tolerance,
            "size_px": args.size_tolerance,
        },
        "fonts": fonts,
        "sizes": args.sizes,
        "scripts": args.scripts,
        "styles": args.styles,
        "failures": [asdict(check) for check in failures],
        "worst": _worst_checks(checks, limit=20),
        "export_checks": export_reports,
        "passed": not failures and all(item["passed"] for item in export_reports),
    }
    report_path = output_dir / "font_matrix_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 0 if report["passed"] else 1


def _selected_fonts(requested: list[str], max_fonts: int) -> list[str]:
    available = sorted(QFontDatabase.families(), key=str.casefold)
    available_by_key = {family.casefold(): family for family in available}
    if len(requested) == 1 and requested[0].casefold() == "all":
        selected = available
    else:
        selected = []
        for family in requested:
            matched = available_by_key.get(family.casefold())
            if matched and matched not in selected:
                selected.append(matched)
    if max_fonts > 0:
        selected = selected[:max_fonts]
    return selected


def _make_blank_video(ffmpeg: str, temp: Path) -> Path:
    path = temp / "blank_960x540.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={BG_HEX}:s=960x540:d=2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return path


def _style_for_case(font_family: str, font_size: int, style_name: str) -> SubtitleStyle:
    style = SubtitleStyle(
        font_family=font_family,
        font_size=font_size,
        font_color="#00FF00",
        stroke_color="#FF00FF",
        shadow_color="#0000FF",
        max_width_percent=88,
    )
    if style_name == "no-stroke":
        style.stroke_enabled = False
        style.shadow_enabled = False
    elif style_name == "heavy-stroke":
        style.stroke_width = 8.0
        style.shadow_offset = 3.0
    elif style_name == "background":
        style.stroke_enabled = False
        style.shadow_enabled = False
        style.background_enabled = True
        style.background_opacity = 42
    elif style_name == "top":
        style.alignment = "top_center"
    elif style_name == "left":
        style.alignment = "bottom_left"
    elif style_name == "right":
        style.alignment = "bottom_right"
    elif style_name == "tight-lines":
        style.line_spacing = -10
    return style


def _check_case(
    video_info: VideoInfo,
    baseline: QImage,
    cue: SubtitleCue,
    style: SubtitleStyle,
    script: str,
    style_name: str,
    *,
    center_tolerance: float,
    size_tolerance: int,
) -> FontMatrixCheck:
    preview = _render_preview(video_info, baseline, cue, style)
    accurate = QImage.fromData(
        render_accurate_preview_frame(
            video_info=video_info,
            cues=[cue],
            style=style,
            position_seconds=0.5,
        )
    )
    preview_box = _subtitle_bbox(baseline, preview)
    render_box = _subtitle_bbox(baseline, accurate)
    center_dx = preview_box["center_x"] - render_box["center_x"]
    center_dy = preview_box["center_y"] - render_box["center_y"]
    width_delta = preview_box["width"] - render_box["width"]
    height_delta = preview_box["height"] - render_box["height"]
    passed = (
        abs(center_dx) <= center_tolerance
        and abs(center_dy) <= center_tolerance
        and abs(width_delta) <= size_tolerance
        and abs(height_delta) <= size_tolerance
    )
    return FontMatrixCheck(
        font_family=style.font_family,
        script=script,
        style_name=style_name,
        font_size=style.font_size,
        preview_box=_compact_box(preview_box),
        render_box=_compact_box(render_box),
        center_dx=round(center_dx, 3),
        center_dy=round(center_dy, 3),
        width_delta=width_delta,
        height_delta=height_delta,
        passed=passed,
    )


def _failed_check(style: SubtitleStyle, script: str, style_name: str, *, error: str) -> FontMatrixCheck:
    return FontMatrixCheck(
        font_family=style.font_family,
        script=script,
        style_name=style_name,
        font_size=style.font_size,
        preview_box={},
        render_box={},
        center_dx=0.0,
        center_dy=0.0,
        width_delta=0,
        height_delta=0,
        passed=False,
        error=error,
    )


def _render_preview(video_info: VideoInfo, baseline: QImage, cue: SubtitleCue, style: SubtitleStyle) -> QImage:
    canvas = VideoSubtitleCanvas()
    canvas.resize(video_info.width, video_info.height)
    canvas.set_video_info(video_info)
    canvas.set_style(style)
    canvas.set_cues([cue])
    image = baseline.copy()
    painter = QPainter(image)
    canvas._draw_subtitle(painter, canvas._video_rect(), cue)
    painter.end()
    return image


def _blank_image(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(BG_HEX))
    return image


def _subtitle_bbox(baseline: QImage, rendered: QImage) -> dict[str, float | int]:
    baseline_arr = _image_array(baseline)
    rendered_arr = _image_array(rendered)
    diff = np.any(
        np.abs(rendered_arr.astype(np.int16) - baseline_arr.astype(np.int16)) > DIFF_THRESHOLD,
        axis=2,
    )
    ys, xs = np.where(diff)
    if len(xs) == 0:
        raise RuntimeError("No subtitle pixels detected.")
    left = int(xs.min())
    top = int(ys.min())
    right = int(xs.max())
    bottom = int(ys.max())
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
        "center_x": (left + right) / 2.0,
        "center_y": (top + bottom) / 2.0,
    }


def _compact_box(box: dict[str, float | int]) -> dict[str, int]:
    return {key: int(box[key]) for key in ("left", "top", "right", "bottom", "width", "height")}


def _image_array(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    buffer = np.frombuffer(converted.bits(), np.uint8)
    return buffer.reshape((converted.height(), converted.width(), 3)).copy()


def _check_render_export_identity(
    ffmpeg: str,
    video_info: VideoInfo,
    cue: SubtitleCue,
    style: SubtitleStyle,
    temp: Path,
) -> dict[str, object]:
    ass_path = temp / f"export_{style.font_family}_{style.font_size}_{cue.index}.ass"
    render_video = temp / f"render_{style.font_family}_{style.font_size}_{cue.index}.mp4"
    export_video = temp / f"export_{style.font_family}_{style.font_size}_{cue.index}.mp4"
    ass_path.write_text(build_ass_document(video_info, [cue], style), encoding="utf-8-sig")
    _render_segment(ffmpeg, video_info.path, ass_path, render_video)
    _render_segment(ffmpeg, video_info.path, ass_path, export_video)
    render_frame = _extract_frame(ffmpeg, render_video)
    export_frame = _extract_frame(ffmpeg, export_video)
    render_arr = _image_array(render_frame)
    export_arr = _image_array(export_frame)
    identical = bool(np.array_equal(render_arr, export_arr))
    return {
        "font_family": style.font_family,
        "font_size": style.font_size,
        "pixel_identical": identical,
        "max_channel_delta": int(np.max(np.abs(render_arr.astype(np.int16) - export_arr.astype(np.int16)))),
        "passed": identical,
    }


def _render_segment(ffmpeg: str, input_video: Path, ass_path: Path, output_video: Path) -> None:
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
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
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))


def _extract_frame(ffmpeg: str, video_path: Path) -> QImage:
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-ss",
            "0.500",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace") or "Could not extract frame.")
    image = QImage.fromData(completed.stdout, "PNG")
    if image.isNull():
        raise RuntimeError(f"Unreadable frame from {video_path}.")
    return image


def _worst_checks(checks: list[FontMatrixCheck], *, limit: int) -> list[dict[str, object]]:
    def score(check: FontMatrixCheck) -> float:
        return max(abs(check.center_dx), abs(check.center_dy), abs(check.width_delta), abs(check.height_delta))

    return [asdict(check) for check in sorted(checks, key=score, reverse=True)[:limit]]


if __name__ == "__main__":
    raise SystemExit(main())
