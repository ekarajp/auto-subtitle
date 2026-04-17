from __future__ import annotations

import re
import subprocess
from pathlib import Path

from core.renderer import ensure_ffmpeg


class AudioAnalysisError(RuntimeError):
    """Raised when FFmpeg cannot analyze audio silence."""


def detect_silences(
    video_path: str | Path,
    *,
    noise_db: int = -35,
    min_silence_duration: float = 0.25,
) -> list[tuple[float, float | None]]:
    """Detect silent ranges using FFmpeg silencedetect.

    Returns a list of (silence_start, silence_end). The final silence may have end=None.
    """
    ffmpeg = ensure_ffmpeg()
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(video_path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_duration:.2f}",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0 and "Output file is empty" not in output:
        raise AudioAnalysisError(output.strip() or "FFmpeg silence detection failed.")

    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", output)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", output)]

    ranges: list[tuple[float, float | None]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else None
        ranges.append((start, end))
    return ranges
