from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from core.ass_builder import build_ass_document
from core.renderer import _escape_filter_path, ensure_ffmpeg
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo


class PreviewRenderError(RuntimeError):
    """Raised when an export-accurate preview frame cannot be rendered."""


def render_accurate_preview_frame(
    *,
    video_info: VideoInfo,
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    position_seconds: float,
) -> bytes:
    """Render one PNG frame using the exact FFmpeg/libass path used by export."""
    ffmpeg = ensure_ffmpeg()
    position_seconds = max(0.0, min(position_seconds, max(0.0, video_info.duration)))

    with tempfile.TemporaryDirectory(prefix="smart_subtitle_preview_") as temp_dir:
        ass_path = Path(temp_dir) / "preview.ass"
        ass_path.write_text(build_ass_document(video_info, cues, style), encoding="utf-8-sig")

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_info.path),
            "-ss",
            f"{position_seconds:.3f}",
            "-vf",
            f"ass='{_escape_filter_path(ass_path)}'",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]

        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise PreviewRenderError(message or "FFmpeg did not return a preview frame.")
        return completed.stdout
