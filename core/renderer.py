from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from utils.timecode import parse_timecode


class RenderError(RuntimeError):
    """Raised when FFmpeg fails to render the video."""


ProgressCallback = Callable[[int, str], None]


def ensure_ffmpeg() -> str:
    executable = _find_winget_executable("ffmpeg.exe") or shutil.which("ffmpeg")
    if not executable:
        executable = _find_winget_executable("ffmpeg.exe")
    if not executable:
        raise RenderError(
            "ffmpeg was not found in PATH. Please install FFmpeg and add its bin folder to PATH."
        )
    return executable


def _find_winget_executable(name: str) -> str | None:
    packages_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if not packages_dir.exists():
        return None
    matches = sorted(packages_dir.glob(f"**/{name}"), key=lambda path: path.stat().st_mtime, reverse=True)
    return str(matches[0]) if matches else None


def render_with_ass(
    *,
    input_video: str | Path,
    ass_file: str | Path,
    output_video: str | Path,
    duration: float,
    progress_callback: ProgressCallback | None = None,
) -> None:
    ffmpeg = ensure_ffmpeg()
    input_path = Path(input_video)
    ass_path = Path(ass_file)
    output_path = Path(output_video)

    if not input_path.exists():
        raise RenderError(f"Video file not found: {input_path}")
    if not ass_path.exists():
        raise RenderError(f"Temporary ASS subtitle file not found: {ass_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_arg = f"ass='{_escape_filter_path(ass_path)}'"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-i",
        str(input_path),
        "-vf",
        filter_arg,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    if progress_callback:
        progress_callback(0, "Starting FFmpeg render...")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output_lines: list[str] = []
    time_re = re.compile(r"time=(\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)")
    assert process.stdout is not None
    for line in process.stdout:
        stripped = line.rstrip()
        output_lines.append(stripped)
        match = time_re.search(stripped)
        if match and duration > 0:
            current = parse_timecode(match.group(1))
            percent = max(0, min(99, int((current / duration) * 100)))
            if progress_callback:
                progress_callback(percent, stripped)
        elif progress_callback and stripped:
            progress_callback(-1, stripped)

    return_code = process.wait()
    if return_code != 0:
        message = "\n".join(output_lines[-20:]) or f"FFmpeg exited with code {return_code}"
        raise RenderError(f"FFmpeg render failed:\n{message}")

    if progress_callback:
        progress_callback(100, f"Export finished: {output_path}")


def _escape_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
