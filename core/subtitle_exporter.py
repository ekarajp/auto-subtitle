from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from core.ass_builder import build_ass_document
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo
from utils.timecode import format_timecode


class SubtitleExportError(RuntimeError):
    """Raised when edited subtitles cannot be exported."""


SUPPORTED_EXPORT_FORMATS = ("srt", "vtt", "ass", "json", "csv", "txt")


def export_subtitle_file(
    path: str | Path,
    cues: list[SubtitleCue],
    *,
    video_info: VideoInfo | None = None,
    style: SubtitleStyle | None = None,
) -> None:
    target = Path(path)
    fmt = target.suffix.lower().lstrip(".")
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise SubtitleExportError(
            f"Unsupported subtitle export format: {fmt or '(none)'}. Use srt, vtt, ass, json, csv, or txt."
        )
    if not cues:
        raise SubtitleExportError("No subtitle cues to export.")

    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "srt":
        content = to_srt(cues)
    elif fmt == "vtt":
        content = to_vtt(cues)
    elif fmt == "ass":
        if video_info is None or style is None:
            raise SubtitleExportError("ASS export requires a selected video and current style.")
        content = build_ass_document(video_info, cues, style)
    elif fmt == "json":
        content = to_json(cues)
    elif fmt == "csv":
        content = to_csv(cues)
    else:
        content = to_txt(cues)

    encoding = "utf-8-sig" if fmt in {"srt", "ass", "csv"} else "utf-8"
    target.write_text(content, encoding=encoding, newline="\n")


def to_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{format_timecode(cue.start, ',')} --> {format_timecode(cue.end, ',')}\n"
            f"{cue.text.strip()}\n"
        )
    return "\n".join(blocks)


def to_vtt(cues: list[SubtitleCue]) -> str:
    blocks = ["WEBVTT\n"]
    for cue in cues:
        blocks.append(
            f"{format_timecode(cue.start, '.')} --> {format_timecode(cue.end, '.')}\n"
            f"{cue.text.strip()}\n"
        )
    return "\n".join(blocks)


def to_json(cues: list[SubtitleCue]) -> str:
    payload = [
        {
            "start": format_timecode(cue.start, "."),
            "end": format_timecode(cue.end, "."),
            "text": cue.text,
        }
        for cue in cues
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_csv(cues: list[SubtitleCue]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["start", "end", "text"], lineterminator="\n")
    writer.writeheader()
    for cue in cues:
        writer.writerow(
            {
                "start": format_timecode(cue.start, "."),
                "end": format_timecode(cue.end, "."),
                "text": cue.text,
            }
        )
    return stream.getvalue()


def to_txt(cues: list[SubtitleCue]) -> str:
    lines = []
    for cue in cues:
        text = cue.text.replace("\n", "\\n")
        lines.append(f"{format_timecode(cue.start, '.')} --> {format_timecode(cue.end, '.')}|{text}")
    return "\n".join(lines) + "\n"
