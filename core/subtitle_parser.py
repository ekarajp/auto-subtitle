from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

from core.subtitle_models import SubtitleCue, SubtitleDocument, SubtitleParseError
from utils.timecode import TimecodeError, parse_timecode


SUPPORTED_FORMATS = ("srt", "vtt", "txt", "csv", "json")
TIMECODE_ARROW_RE = re.compile(r"\s*-->\s*")


def detect_subtitle_format(path: str | Path) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix if suffix in SUPPORTED_FORMATS else "unknown"


def parse_subtitle_file(
    path: str | Path,
    *,
    subtitle_format: str | None = None,
    video_duration: float | None = None,
    txt_mode: str = "auto",
    txt_fixed_duration: float = 3.0,
) -> SubtitleDocument:
    subtitle_path = Path(path)
    if not subtitle_path.exists():
        raise SubtitleParseError(f"ไม่พบไฟล์ subtitle: {subtitle_path}")

    fmt = (subtitle_format or detect_subtitle_format(subtitle_path)).lower()
    if fmt == "auto":
        fmt = detect_subtitle_format(subtitle_path)
    if fmt not in SUPPORTED_FORMATS:
        raise SubtitleParseError(
            f"ไม่รองรับไฟล์ subtitle format '{fmt}'. รองรับ: {', '.join(SUPPORTED_FORMATS)}"
        )

    try:
        text = subtitle_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = subtitle_path.read_text(encoding="cp874")
        except UnicodeDecodeError as exc:
            raise SubtitleParseError("อ่านไฟล์ subtitle ไม่ได้ กรุณาบันทึกไฟล์เป็น UTF-8") from exc
    except OSError as exc:
        raise SubtitleParseError(f"เปิดไฟล์ subtitle ไม่ได้: {exc}") from exc

    if fmt == "srt":
        cues = _parse_srt(text)
    elif fmt == "vtt":
        cues = _parse_vtt(text)
    elif fmt == "txt":
        cues = _parse_txt(
            text,
            video_duration=video_duration,
            txt_mode=txt_mode,
            fixed_duration=txt_fixed_duration,
        )
    elif fmt == "csv":
        cues = _parse_csv(text)
    else:
        cues = _parse_json(text)

    if not cues:
        raise SubtitleParseError("ไม่พบ subtitle cue ที่อ่านได้ในไฟล์นี้")

    return SubtitleDocument(cues=cues, source_format=fmt)


def _parse_srt(text: str) -> list[SubtitleCue]:
    blocks = _split_blocks(text)
    cues: list[SubtitleCue] = []
    for block_no, block in enumerate(blocks, start=1):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        time_line_index = 0
        if len(lines) > 1 and lines[0].strip().isdigit():
            time_line_index = 1
        if time_line_index >= len(lines) or "-->" not in lines[time_line_index]:
            raise SubtitleParseError(f"SRT block {block_no}: ไม่พบ timecode '-->'")

        start, end = _parse_time_range(lines[time_line_index], f"SRT block {block_no}")
        subtitle_text = "\n".join(lines[time_line_index + 1 :]).strip()
        if not subtitle_text:
            raise SubtitleParseError(f"SRT block {block_no}: ไม่มีข้อความ subtitle")
        cues.append(SubtitleCue(len(cues) + 1, start, end, subtitle_text))
    return cues


def _parse_vtt(text: str) -> list[SubtitleCue]:
    cleaned_lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped == "WEBVTT" or stripped.startswith(("NOTE", "STYLE", "REGION")):
            continue
        cleaned_lines.append(line)

    blocks = _split_blocks("\n".join(cleaned_lines))
    cues: list[SubtitleCue] = []
    for block_no, block in enumerate(blocks, start=1):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_line_index = 0
        if "-->" not in lines[0] and len(lines) > 1:
            time_line_index = 1
        if "-->" not in lines[time_line_index]:
            continue
        start, end = _parse_time_range(lines[time_line_index], f"VTT block {block_no}")
        subtitle_text = "\n".join(
            _strip_vtt_tags(line) for line in lines[time_line_index + 1 :]
        ).strip()
        if subtitle_text:
            cues.append(SubtitleCue(len(cues) + 1, start, end, subtitle_text))
    return cues


def _parse_txt(
    text: str,
    *,
    video_duration: float | None,
    txt_mode: str,
    fixed_duration: float,
) -> list[SubtitleCue]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    timestamped = txt_mode == "timestamped" or (
        txt_mode == "auto" and all("-->" in line and "|" in line for line in lines)
    )
    if timestamped:
        cues: list[SubtitleCue] = []
        for line_no, line in enumerate(lines, start=1):
            if "|" not in line:
                raise SubtitleParseError(
                    f"TXT line {line_no}: รูปแบบ timestamped ต้องเป็น 'start --> end|text'"
                )
            range_part, subtitle_text = line.split("|", 1)
            start, end = _parse_time_range(range_part, f"TXT line {line_no}")
            cues.append(SubtitleCue(len(cues) + 1, start, end, subtitle_text))
        return cues

    if fixed_duration <= 0:
        raise SubtitleParseError("TXT fixed duration ต้องมากกว่า 0 วินาที")

    cues = []
    if txt_mode in {"plain_auto", "auto"} and video_duration and video_duration > 0:
        slot = video_duration / len(lines)
        for idx, line in enumerate(lines):
            start = idx * slot
            end = min(video_duration, (idx + 1) * slot)
            if end <= start:
                end = start + fixed_duration
            cues.append(SubtitleCue(idx + 1, start, end, line))
    else:
        for idx, line in enumerate(lines):
            start = idx * fixed_duration
            cues.append(SubtitleCue(idx + 1, start, start + fixed_duration, line))
    return cues


def _parse_csv(text: str) -> list[SubtitleCue]:
    lines = text.lstrip("\ufeff").splitlines()
    reader = csv.DictReader(lines)
    required = {"start", "end", "text"}
    fieldnames = {name.strip() for name in (reader.fieldnames or [])}
    cues: list[SubtitleCue] = []

    if required.issubset(fieldnames):
        for row_no, row in enumerate(reader, start=2):
            normalized = {key.strip(): value for key, value in row.items() if key}
            cues.append(
                _csv_cue(
                    row_no,
                    normalized.get("start", ""),
                    normalized.get("end", ""),
                    normalized.get("text", ""),
                    len(cues) + 1,
                )
            )
        return cues

    # Also accept bare 3-column CSV rows: start,end,text
    bare_reader = csv.reader(lines)
    for row_no, row in enumerate(bare_reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) < 3:
            raise SubtitleParseError("CSV ต้องมี columns: start,end,text")
        cues.append(_csv_cue(row_no, row[0], row[1], ",".join(row[2:]), len(cues) + 1))
    return cues


def _csv_cue(row_no: int, start_value: str, end_value: str, text: str, index: int) -> SubtitleCue:
    try:
        start = parse_timecode(start_value)
        end = parse_timecode(end_value)
    except TimecodeError as exc:
        raise SubtitleParseError(f"CSV row {row_no}: {exc}") from exc
    return SubtitleCue(index, start, end, text)


def _parse_json(text: str) -> list[SubtitleCue]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SubtitleParseError(f"JSON parse error line {exc.lineno}: {exc.msg}") from exc

    if not isinstance(payload, list):
        raise SubtitleParseError("JSON ต้องเป็น array ของ object ที่มี start, end, text")

    cues: list[SubtitleCue] = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise SubtitleParseError(f"JSON item {idx}: ต้องเป็น object")
        try:
            start = parse_timecode(item["start"])
            end = parse_timecode(item["end"])
            subtitle_text = str(item["text"])
        except KeyError as exc:
            raise SubtitleParseError(f"JSON item {idx}: ไม่มี field {exc.args[0]!r}") from exc
        except TimecodeError as exc:
            raise SubtitleParseError(f"JSON item {idx}: {exc}") from exc
        cues.append(SubtitleCue(idx, start, end, subtitle_text))
    return cues


def _parse_time_range(line: str, context: str) -> tuple[float, float]:
    parts = TIMECODE_ARROW_RE.split(line, maxsplit=1)
    if len(parts) != 2:
        raise SubtitleParseError(f"{context}: timecode ต้องมี '-->'")
    end_token = parts[1].strip().split()[0]
    try:
        start = parse_timecode(parts[0].strip())
        end = parse_timecode(end_token)
    except TimecodeError as exc:
        raise SubtitleParseError(f"{context}: {exc}") from exc
    return start, end


def _split_blocks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    return [block for block in re.split(r"\n\s*\n", normalized) if block.strip()]


def _strip_vtt_tags(line: str) -> str:
    return re.sub(r"<[^>]+>", "", line)


def cues_to_plain_lines(cues: Iterable[SubtitleCue]) -> list[str]:
    return [cue.text for cue in cues]
