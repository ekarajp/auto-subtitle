from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from core.ass_builder import build_ass_document
from core.renderer import _escape_filter_path, ensure_ffmpeg
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo


class PreviewRenderError(RuntimeError):
    """Raised when an export-accurate preview frame cannot be rendered."""


_CONFIGURED_PREVIEW_CACHE_DIR: Path | None = None


def default_preview_cache_dir() -> Path:
    """Return the default directory for FFmpeg/libass preview-frame cache files."""
    return Path(tempfile.gettempdir()) / "smart_subtitle_quality_preview_cache"


def set_preview_cache_dir(path: str | Path | None) -> Path | None:
    """Configure the process-wide cache directory used by accurate preview frames."""
    global _CONFIGURED_PREVIEW_CACHE_DIR
    if path is None or str(path).strip() == "":
        _CONFIGURED_PREVIEW_CACHE_DIR = None
        return None
    cache_dir = Path(path).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    _CONFIGURED_PREVIEW_CACHE_DIR = cache_dir
    return cache_dir


def get_preview_cache_dir() -> Path | None:
    return _CONFIGURED_PREVIEW_CACHE_DIR


def _cue_payload(cue: SubtitleCue) -> dict[str, object]:
    return {
        "index": cue.index,
        "start": round(cue.start, 3),
        "end": round(cue.end, 3),
        "text": cue.text,
        "style_overrides": cue.style_overrides,
    }


def _video_payload(video_info: VideoInfo) -> dict[str, object]:
    path = Path(video_info.path)
    try:
        stat = path.stat()
        file_payload = {
            "path": str(path.resolve()),
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    except OSError:
        file_payload = {"path": str(path)}
    return {
        **file_payload,
        "width": video_info.width,
        "height": video_info.height,
        "duration": round(video_info.duration, 3),
        "fps": video_info.fps,
        "codec": video_info.codec,
    }


def preview_frame_cache_key(
    *,
    video_info: VideoInfo,
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    position_seconds: float,
    ass_document: str,
    cache_key_extra: str = "",
) -> str:
    payload = {
        "version": 2,
        "video": _video_payload(video_info),
        "cues": [_cue_payload(cue) for cue in cues],
        "style": style.to_dict(),
        "position_ms": round(position_seconds * 1000),
        "ass_sha256": hashlib.sha256(ass_document.encode("utf-8")).hexdigest(),
        "extra": cache_key_extra,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_accurate_preview_frame(
    *,
    video_info: VideoInfo,
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    position_seconds: float,
    cache_dir: str | Path | None = None,
    cache_key_extra: str = "",
    cancel_event: threading.Event | None = None,
) -> bytes:
    """Render one PNG frame using the exact FFmpeg/libass path used by export."""
    ffmpeg = ensure_ffmpeg()
    position_seconds = max(0.0, min(position_seconds, max(0.0, video_info.duration)))
    ass_document = build_ass_document(video_info, cues, style)
    resolved_cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir else _CONFIGURED_PREVIEW_CACHE_DIR
    cache_path: Path | None = None
    if resolved_cache_dir:
        resolved_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = preview_frame_cache_key(
            video_info=video_info,
            cues=cues,
            style=style,
            position_seconds=position_seconds,
            ass_document=ass_document,
            cache_key_extra=cache_key_extra,
        )
        cache_path = resolved_cache_dir / f"{cache_key}.png"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path.read_bytes()

    with tempfile.TemporaryDirectory(prefix="smart_subtitle_preview_") as temp_dir:
        ass_path = Path(temp_dir) / "preview.ass"
        ass_path.write_text(ass_document, encoding="utf-8-sig")

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

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = _communicate_preview_process(process, timeout=15.0, cancel_event=cancel_event)
        except subprocess.TimeoutExpired as exc:
            raise PreviewRenderError("FFmpeg preview frame render timed out.") from exc
        except PreviewRenderError:
            raise
        if process.returncode != 0 or not stdout:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise PreviewRenderError(message or "FFmpeg did not return a preview frame.")
        if cache_path:
            cache_path.write_bytes(stdout)
        return stdout


def _communicate_preview_process(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
    cancel_event: threading.Event | None,
) -> tuple[bytes, bytes]:
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event is not None and cancel_event.is_set():
            _stop_preview_process(process)
            raise PreviewRenderError("Preview render was cancelled.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_preview_process(process)
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.communicate(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue


def _stop_preview_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
