from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


class VideoProbeError(RuntimeError):
    """Raised when ffprobe cannot read video metadata."""


@dataclass(slots=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    duration: float
    fps: float
    codec: str = ""

    @property
    def aspect_ratio_value(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def orientation(self) -> str:
        ratio = self.aspect_ratio_value
        if math.isclose(ratio, 1.0, rel_tol=0.04):
            return "square"
        if ratio > 1.0:
            return "landscape"
        return "portrait"

    @property
    def aspect_ratio_label(self) -> str:
        if self.width <= 0 or self.height <= 0:
            return "unknown"
        ratio = self.aspect_ratio_value
        if math.isclose(ratio, 16 / 9, rel_tol=0.04):
            return "16:9"
        if math.isclose(ratio, 9 / 16, rel_tol=0.04):
            return "9:16"
        if math.isclose(ratio, 1.0, rel_tol=0.04):
            return "1:1"
        divisor = math.gcd(self.width, self.height)
        return f"{self.width // divisor}:{self.height // divisor}"


def ensure_ffprobe() -> str:
    executable = shutil.which("ffprobe")
    if executable:
        return executable

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe")
        if sibling.exists():
            return str(sibling)

    winget_probe = _find_winget_executable("ffprobe.exe")
    if winget_probe:
        return winget_probe

    raise VideoProbeError(
        "ไม่พบ ffprobe ใน PATH กรุณาติดตั้ง FFmpeg แบบเต็ม และเพิ่มโฟลเดอร์ bin ลง PATH"
    )


def _find_winget_executable(name: str) -> str | None:
    packages_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if not packages_dir.exists():
        return None
    matches = sorted(packages_dir.glob(f"**/{name}"), key=lambda path: path.stat().st_mtime, reverse=True)
    return str(matches[0]) if matches else None


def probe_video(path: str | Path) -> VideoInfo:
    video_path = Path(path)
    if not video_path.exists():
        raise VideoProbeError(f"ไม่พบไฟล์วิดีโอ: {video_path}")

    try:
        ffprobe = ensure_ffprobe()
    except VideoProbeError:
        return _probe_video_with_ffmpeg(video_path)

    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,codec_name:format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise VideoProbeError(f"ffprobe อ่าน metadata ไม่ได้: {message}") from exc

    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        fmt = payload.get("format", {})
        width = int(stream["width"])
        height = int(stream["height"])
        duration = float(fmt.get("duration") or 0)
        fps = _parse_fraction(stream.get("r_frame_rate", "0/1"))
        codec = stream.get("codec_name", "")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VideoProbeError("ffprobe ส่งข้อมูล metadata ไม่ครบหรืออ่านไม่ได้") from exc

    if width <= 0 or height <= 0:
        raise VideoProbeError("ไม่สามารถอ่านความละเอียดวิดีโอได้")

    return VideoInfo(video_path, width, height, duration, fps, codec)


def _parse_fraction(value: str) -> float:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _probe_video_with_ffmpeg(video_path: Path) -> VideoInfo:
    """Fallback metadata reader for machines that have ffmpeg but not ffprobe."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoProbeError(
            "ไม่พบทั้ง ffprobe และ ffmpeg ใน PATH กรุณาติดตั้ง FFmpeg และเพิ่มโฟลเดอร์ bin ลง PATH"
        )

    command = [ffmpeg, "-hide_banner", "-i", str(video_path)]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = f"{result.stdout}\n{result.stderr}"

    duration = _parse_ffmpeg_duration(output)
    stream_match = re.search(
        r"Video:\s*(?P<codec>[^,\n]+).*?(?P<width>\d{2,5})x(?P<height>\d{2,5}).*?(?P<fps>\d+(?:\.\d+)?)\s*fps",
        output,
        re.IGNORECASE | re.DOTALL,
    )
    if not stream_match:
        raise VideoProbeError(
            "อ่าน metadata ด้วย ffmpeg ไม่ได้ และไม่พบ ffprobe กรุณาติดตั้ง FFmpeg แบบเต็มที่มี ffprobe.exe"
        )

    return VideoInfo(
        path=video_path,
        width=int(stream_match.group("width")),
        height=int(stream_match.group("height")),
        duration=duration,
        fps=float(stream_match.group("fps")),
        codec=stream_match.group("codec").strip(),
    )


def _parse_ffmpeg_duration(output: str) -> float:
    match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?", output)
    if not match:
        return 0.0
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000
