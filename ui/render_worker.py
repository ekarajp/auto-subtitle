from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from core.preview_renderer import render_accurate_preview_frame
from core.ass_builder import build_ass_document
from core.renderer import render_with_ass
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo


class RenderWorker(QObject):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        video_info: VideoInfo,
        cues: list[SubtitleCue],
        style: SubtitleStyle,
        output_path: str,
    ) -> None:
        super().__init__()
        self.video_info = video_info
        self.cues = cues
        self.style = style
        self.output_path = output_path

    @Slot()
    def run(self) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="smart_subtitle_") as temp_dir:
                ass_path = Path(temp_dir) / "subtitle.ass"
                ass_text = build_ass_document(self.video_info, self.cues, self.style)
                ass_path.write_text(ass_text, encoding="utf-8-sig")

                def callback(percent: int, line: str) -> None:
                    if percent >= 0:
                        self.progress.emit(percent)
                    if line:
                        self.log.emit(line)

                render_with_ass(
                    input_video=self.video_info.path,
                    ass_file=ass_path,
                    output_video=self.output_path,
                    duration=self.video_info.duration,
                    progress_callback=callback,
                )
            self.finished.emit(self.output_path)
        except Exception as exc:  # GUI boundary: keep error readable for users.
            self.failed.emit(str(exc))


class ExactPreviewFrameWorker(QObject):
    finished = Signal(int, object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        video_info: VideoInfo,
        cues: list[SubtitleCue],
        style: SubtitleStyle,
        position_ms: int,
        cache_dir: Path,
    ) -> None:
        super().__init__()
        self.video_info = video_info
        self.cues = [
            SubtitleCue(cue.index, cue.start, cue.end, cue.text, dict(cue.style_overrides))
            for cue in cues
        ]
        self.style = SubtitleStyle.from_dict(style.to_dict())
        self.position_ms = max(0, int(position_ms))
        self.cache_dir = Path(cache_dir)

    @Slot()
    def run(self) -> None:
        try:
            png_bytes = render_accurate_preview_frame(
                video_info=self.video_info,
                cues=self.cues,
                style=self.style,
                position_seconds=self.position_ms / 1000.0,
                cache_dir=self.cache_dir,
            )
            self.finished.emit(self.position_ms, png_bytes)
        except Exception as exc:  # GUI boundary: keep error readable for users.
            self.failed.emit(str(exc))
