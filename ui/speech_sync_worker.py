from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from core.speech_sync import SpeechSyncOptions, SpeechSyncResult, transcribe_video_to_cues
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo


class SpeechSyncWorker(QObject):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        video_info: VideoInfo,
        style: SubtitleStyle,
        options: SpeechSyncOptions,
        source_cues: list[SubtitleCue] | None = None,
    ) -> None:
        super().__init__()
        self.video_info = video_info
        self.style = style
        self.options = options
        self.source_cues = list(source_cues or [])

    @Slot()
    def run(self) -> None:
        try:
            def callback(percent: int, message: str) -> None:
                self.progress.emit(percent)
                if message:
                    self.log.emit(message)

            result: SpeechSyncResult = transcribe_video_to_cues(
                self.video_info,
                self.style,
                options=self.options,
                source_cues=self.source_cues,
                progress_callback=callback,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
