from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSignalBlocker, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget

from core.subtitle_layout import (
    preview_baseline_shift,
    preview_stroke_width,
    style_for_ass_export,
    style_for_preview,
    subtitle_line_height,
    subtitle_line_positions,
    subtitle_max_width,
    wrap_subtitle_text,
)
from core.style_preset import (
    SubtitleStyle,
    style_with_overrides,
)
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo
from utils.timecode import format_timecode


class VideoSubtitleCanvas(QWidget):
    """Paints the current video frame and subtitle in one widget.

    Drawing both layers in one paint event avoids the common Windows issue where
    native video widgets appear above transparent overlay widgets.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setAutoFillBackground(False)
        self._video_info: VideoInfo | None = None
        self._style = SubtitleStyle()
        self._cues: list[SubtitleCue] = []
        self._selected_cue: SubtitleCue | None = None
        self._force_selected_preview = False
        self._position_seconds = 0.0
        self._frame_image: QImage | None = None
        self._frame_has_subtitles = False
        self._source_has_subtitles = False
        self._fit_mode = "fit"
        self._fit_margin_percent = 0

    def set_video_info(self, info: VideoInfo | None) -> None:
        self._video_info = info
        self.update()

    def set_source_has_subtitles(self, enabled: bool) -> None:
        self._source_has_subtitles = enabled
        self.update()

    def set_style(self, style: SubtitleStyle) -> None:
        self._style = style
        self.update()

    def set_cues(self, cues: list[SubtitleCue]) -> None:
        self._cues = cues
        self.update()

    def set_selected_cue(self, cue: SubtitleCue | None, *, force_preview: bool = True) -> None:
        self._selected_cue = cue
        self._force_selected_preview = bool(cue and force_preview)
        if cue:
            self._position_seconds = cue.start
        self.update()

    def clear_forced_selected_preview(self) -> None:
        self._force_selected_preview = False
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position_seconds = max(0.0, seconds)
        self.update()

    def set_frame_image(self, image: QImage, *, has_subtitles: bool = False) -> None:
        self._frame_image = image.copy()
        self._frame_has_subtitles = has_subtitles
        self.update()

    def set_fit_options(self, mode: str, margin_percent: int) -> None:
        self._fit_mode = mode
        self._fit_margin_percent = max(0, min(30, int(margin_percent)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor("#242A31"))

        video_rect = self._video_rect()
        if self._frame_image and not self._frame_image.isNull():
            painter.drawImage(video_rect, self._frame_image)
        else:
            painter.fillRect(video_rect, QColor("#242A31"))
            painter.setPen(QColor("#CBD5DF"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(video_rect, Qt.AlignmentFlag.AlignCenter, "Select a video, then press Play")

        painter.setPen(QPen(QColor("#D7DEE7"), 1))
        painter.drawRect(video_rect.adjusted(0, 0, -1, -1))

        cue = self._active_cue()
        if cue and self._video_info and not self._frame_has_subtitles and not self._source_has_subtitles:
            self._draw_subtitle(painter, video_rect, cue)
        painter.end()

    def _active_cue(self) -> SubtitleCue | None:
        # Prefer the row the user explicitly selected so Preview Selected is immediate.
        if self._force_selected_preview and self._selected_cue:
            return self._selected_cue
        if self._selected_cue and self._selected_cue.start <= self._position_seconds <= self._selected_cue.end:
            return self._selected_cue
        for cue in self._cues:
            if cue.start <= self._position_seconds <= cue.end:
                return cue
        return None

    def _video_rect(self):
        available = self.rect()
        if self._fit_mode == "fit_margin" and self._fit_margin_percent > 0:
            margin_x = round(available.width() * self._fit_margin_percent / 100)
            margin_y = round(available.height() * self._fit_margin_percent / 100)
            available = available.adjusted(margin_x, margin_y, -margin_x, -margin_y)
            if available.width() <= 20 or available.height() <= 20:
                available = self.rect()
        if not self._video_info:
            ratio = 16 / 9
        else:
            ratio = self._video_info.aspect_ratio_value or 16 / 9

        width = available.width()
        height = width / ratio
        if height > available.height():
            height = available.height()
            width = height * ratio

        x = available.left() + (available.width() - width) / 2
        y = available.top() + (available.height() - height) / 2
        return available.__class__(round(x), round(y), round(width), round(height))

    def _draw_subtitle(self, painter: QPainter, video_rect, cue: SubtitleCue) -> None:
        assert self._video_info is not None
        wrap_style = style_with_overrides(self._style, cue.style_overrides)
        style = style_for_preview(wrap_style)
        layout_style = style_for_ass_export(wrap_style)
        scale_x = video_rect.width() / max(1, self._video_info.width)
        scale_y = video_rect.height() / max(1, self._video_info.height)
        lines = wrap_subtitle_text(cue.text, self._video_info, wrap_style, limit_lines=False)
        positions = subtitle_line_positions(self._video_info, layout_style, len(lines), renderer="ass")

        font_size = max(1, round(style.font_size * scale_y))
        font = QFont(style.font_family)
        font.setPixelSize(font_size)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        painter.setFont(font)

        source_line_height = subtitle_line_height(layout_style)
        line_height = source_line_height * scale_y
        max_width = subtitle_max_width(self._video_info, layout_style)
        max_width_view = max_width * scale_x
        box_padding_x = max(8, round(layout_style.font_size * 0.45 * scale_x))
        box_padding_y = max(5, round(layout_style.font_size * 0.24 * scale_y))

        if style.background_enabled and lines:
            bg = QColor(style.background_color)
            bg.setAlpha(round(255 * style.background_opacity / 100))
            painter.setBrush(bg)
            painter.setPen(Qt.PenStyle.NoPen)
            first_x, first_y, an = positions[0]
            last_y = positions[min(len(positions), len(lines)) - 1][1]
            first_x_view = video_rect.left() + first_x * scale_x
            first_y_view = video_rect.top() + first_y * scale_y
            last_y_view = video_rect.top() + last_y * scale_y
            if an == 4:
                left = round(first_x_view - box_padding_x)
            elif an == 6:
                left = round(first_x_view - max_width_view - box_padding_x)
            else:
                left = round(first_x_view - max_width_view / 2 - box_padding_x)
            top = round(first_y_view - line_height / 2 - box_padding_y)
            width = round(max_width_view + (box_padding_x * 2))
            height = round((last_y_view - first_y_view) + line_height + (box_padding_y * 2))
            painter.drawRoundedRect(left, top, width, height, 6, 6)

        for line, (x, y, an) in zip(lines, positions):
            x_view = video_rect.left() + x * scale_x
            y_view = video_rect.top() + y * scale_y
            if an == 4:
                left = x_view
            elif an == 6:
                left = x_view - max_width_view
            else:
                left = x_view - max_width_view / 2
            text_rect = video_rect.__class__(
                round(left),
                round(y_view - line_height / 2),
                round(max_width_view),
                round(line_height),
            )
            if style.shadow_enabled and style.shadow_offset > 0:
                shadow = QColor(style.shadow_color)
                shadow.setAlpha(220)
                offset = max(2, round(style.shadow_offset * scale_y))
                blur_steps = max(1, min(4, round(style.shadow_blur)))
                for step in range(blur_steps):
                    spread = step if blur_steps > 1 else 0
                    alpha = max(70, 220 - (step * 40))
                    shadow.setAlpha(alpha)
                    self._draw_text_path(
                        painter,
                        text_rect.translated(offset + spread, offset + spread),
                        line,
                        font,
                        ass_alignment=an,
                        fill_color=shadow,
                        stroke_color=None,
                        stroke_width=0,
                    )

            self._draw_text_path(
                painter,
                text_rect,
                line,
                font,
                ass_alignment=an,
                fill_color=QColor(style.font_color),
                stroke_color=QColor(style.stroke_color) if style.stroke_enabled and style.stroke_width > 0 else None,
                stroke_width=preview_stroke_width(style.stroke_width, scale_y) if style.stroke_enabled else 0,
            )

    def _fit_font_size(self, lines: list[str], family: str, start_size: int, max_width: float) -> int:
        size = start_size
        while size > 8:
            metrics = QFontMetrics(QFont(family, size))
            widest = max((metrics.horizontalAdvance(line) for line in lines), default=0)
            if widest <= max_width:
                return size
            size -= 1
        return size

    def _draw_text_path(
        self,
        painter: QPainter,
        text_rect,
        text: str,
        font: QFont,
        *,
        ass_alignment: int,
        fill_color: QColor,
        stroke_color: QColor | None,
        stroke_width: int,
    ) -> None:
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(text)
        if ass_alignment == 4:
            x = text_rect.left()
        elif ass_alignment == 6:
            x = text_rect.right() - text_width
        else:
            x = text_rect.left() + (text_rect.width() - text_width) / 2
        y = text_rect.top() + (text_rect.height() + metrics.ascent() - metrics.descent()) / 2
        y += preview_baseline_shift(max(1, font.pixelSize()))
        painter.setFont(font)
        if stroke_color and stroke_width > 0:
            painter.setPen(stroke_color)
            for radius in range(1, stroke_width + 1):
                offsets = [
                    (-radius, 0),
                    (radius, 0),
                    (0, -radius),
                    (0, radius),
                    (-radius, -radius),
                    (-radius, radius),
                    (radius, -radius),
                    (radius, radius),
                ]
                for dx, dy in offsets:
                    painter.drawText(QPointF(x + dx, y + dy), text)
        painter.setPen(fill_color)
        painter.drawText(QPointF(x, y), text)


class SubtitlePreviewWidget(QWidget):
    """Real-time video preview using the same subtitle data that will be exported."""

    activeCueChanged = Signal(int)
    accuratePreviewRequested = Signal(int)
    accurateVideoRequested = Signal()

    def __init__(self, parent: QWidget | None = None, *, allow_fullscreen: bool = True) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self._video_info: VideoInfo | None = None
        self._video_path: Path | None = None
        self._original_video_path: Path | None = None
        self._source_has_subtitles = False
        self._style = SubtitleStyle()
        self._cues: list[SubtitleCue] = []
        self._accept_frames = True
        self._play_requested = False
        self._full_preview_dialog: QDialog | None = None
        self._last_active_cue_index = -1

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.35)
        self.player.setAudioOutput(self.audio_output)

        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self._video_frame_changed)
        self.player.setVideoSink(self.video_sink)

        self.canvas = VideoSubtitleCanvas()

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_playback)

        self.full_preview_button = QPushButton("Full Preview")
        self.full_preview_button.clicked.connect(self.open_full_preview)
        self.full_preview_button.setVisible(allow_fullscreen)

        self.accurate_preview_button = QPushButton("Exact Frame")
        self.accurate_preview_button.setToolTip("Render this frame with FFmpeg/libass, the same engine used by export.")
        self.accurate_preview_button.clicked.connect(self.request_accurate_preview)

        self.accurate_video_button = QPushButton("Render Preview")
        self.accurate_video_button.setToolTip("Render a temporary preview video with FFmpeg/libass, then play it here.")
        self.accurate_video_button.clicked.connect(self.request_accurate_video)

        self.fit_mode_combo = QComboBox()
        self.fit_mode_combo.addItem("Fit", "fit")
        self.fit_mode_combo.addItem("Fit Margin", "fit_margin")
        self.fit_mode_combo.currentIndexChanged.connect(self._fit_options_changed)

        self.fit_margin_spin = QSpinBox()
        self.fit_margin_spin.setRange(0, 30)
        self.fit_margin_spin.setValue(6)
        self.fit_margin_spin.setSuffix("%")
        self.fit_margin_spin.setToolTip("Preview margin only. Export uses the subtitle safe-area settings.")
        self.fit_margin_spin.valueChanged.connect(self._fit_options_changed)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.seek_to)

        self.time_label = QLabel("00:00:00.000 / 00:00:00.000")
        self.time_label.setMinimumWidth(190)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.controls_bar = QWidget()
        self.controls_bar.setObjectName("PreviewControlsBar")
        self.controls_bar.setMinimumHeight(84)
        self.controls_bar.setStyleSheet(
            "QWidget#PreviewControlsBar { background: #111820; border-top: 1px solid #34404C; } "
            "QPushButton { background: #F3F6FA; color: #111820; border: 1px solid #7E8A98; "
            "border-radius: 6px; min-height: 30px; padding: 4px 12px; font-weight: 600; } "
            "QPushButton:hover { background: #DCEBFF; } "
            "QComboBox, QSpinBox { background: #FFFFFF; color: #111820; border: 1px solid #7E8A98; "
            "border-radius: 6px; padding: 3px 6px; min-height: 28px; } "
            "QSlider::groove:horizontal { height: 6px; background: #C9D2DC; border-radius: 3px; } "
            "QSlider::handle:horizontal { background: #2B83D3; width: 16px; margin: -5px 0; border-radius: 8px; } "
            "QLabel { color: #F3F6FA; }"
        )
        controls = QVBoxLayout(self.controls_bar)
        controls.setContentsMargins(10, 6, 10, 8)
        controls.setSpacing(6)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self.play_button)
        button_row.addWidget(self.full_preview_button)
        button_row.addWidget(self.accurate_preview_button)
        button_row.addWidget(self.accurate_video_button)
        button_row.addStretch(1)
        button_row.addWidget(self.fit_mode_combo)
        button_row.addWidget(self.fit_margin_spin)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)
        slider_row.addWidget(self.position_slider, 1)
        slider_row.addWidget(self.time_label)

        controls.addLayout(button_row)
        controls.addLayout(slider_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.controls_bar)

        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)

    def set_video_info(self, info: VideoInfo | None) -> None:
        self._video_info = info
        self.canvas.set_video_info(info)

    def set_video_path(self, path: str | Path, *, source_has_subtitles: bool = False) -> None:
        self._video_path = Path(path).resolve()
        self._source_has_subtitles = source_has_subtitles
        if not source_has_subtitles:
            self._original_video_path = self._video_path
        self.canvas.set_source_has_subtitles(source_has_subtitles)
        self.player.setSource(QUrl.fromLocalFile(str(self._video_path)))
        self.seek_to(0)

    def reset_to_original_video(self) -> None:
        if self._source_has_subtitles and self._original_video_path:
            self.set_video_path(self._original_video_path, source_has_subtitles=False)

    def set_style(self, style: SubtitleStyle) -> None:
        self._style = SubtitleStyle.from_dict(style.to_dict())
        self.canvas.set_style(style)

    def set_cues(self, cues: list[SubtitleCue]) -> None:
        self._cues = list(cues)
        self._last_active_cue_index = -1
        self.canvas.set_cues(cues)

    def set_sample_cue(self, cue: SubtitleCue | None) -> None:
        self.canvas.set_selected_cue(cue, force_preview=True)
        if cue:
            self.seek_to(round(cue.start * 1000), clear_forced_preview=False)

    def seek_to(self, milliseconds: int, *, clear_forced_preview: bool = True) -> None:
        milliseconds = max(0, milliseconds)
        duration = self.player.duration()
        if duration > 0:
            milliseconds = min(milliseconds, duration)
        if clear_forced_preview:
            self.canvas.clear_forced_selected_preview()
        # A paused QMediaPlayer can still deliver one decoded frame after a seek.
        # Keep frame acceptance open so selecting a subtitle updates the still image.
        self._accept_frames = True
        self.player.setPosition(milliseconds)
        self.canvas.set_position(milliseconds / 1000.0)
        self._update_time_label(milliseconds, self.player.duration())

    def show_accurate_preview_image(self, image: QImage, milliseconds: int) -> None:
        self.pause_playback()
        self.player.setPosition(max(0, milliseconds))
        self.canvas.set_frame_image(image, has_subtitles=True)
        self._update_time_label(milliseconds, self.player.duration())

    def request_accurate_preview(self) -> None:
        self.pause_playback()
        self.accuratePreviewRequested.emit(self.player.position())

    def request_accurate_video(self) -> None:
        self.pause_playback()
        self.accurateVideoRequested.emit()

    def toggle_playback(self) -> None:
        if self._play_requested:
            self.pause_playback()
        else:
            self._play_requested = True
            self._accept_frames = True
            self.canvas.clear_forced_selected_preview()
            self.player.play()
            self.play_button.setText("Pause")

    def pause_playback(self) -> None:
        self._play_requested = False
        self._accept_frames = False
        current_position = self.player.position()
        self.player.pause()
        self.player.setPosition(current_position)
        self.canvas.set_position(current_position / 1000.0)
        self.play_button.setText("Play")

    def open_full_preview(self) -> None:
        if not self._video_path or not self._video_info:
            return
        if self._full_preview_dialog is not None:
            self._full_preview_dialog.close()
            self._full_preview_dialog = None

        current_position = self.player.position()
        self.pause_playback()

        dialog = QDialog(self)
        self._full_preview_dialog = dialog
        dialog.setWindowTitle("Full Preview - Smart Subtitle")
        dialog.setModal(False)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 36)

        preview = SubtitlePreviewWidget(dialog, allow_fullscreen=False)
        preview.set_video_info(self._video_info)
        preview.set_style(self._style)
        preview.set_cues(self._cues)
        preview.set_video_path(self._video_path)
        preview.canvas.set_fit_options(
            str(self.fit_mode_combo.currentData()),
            int(self.fit_margin_spin.value()),
        )
        preview.fit_mode_combo.setCurrentIndex(self.fit_mode_combo.currentIndex())
        preview.fit_margin_spin.setValue(self.fit_margin_spin.value())
        preview.seek_to(current_position)
        preview.controls_bar.setMinimumHeight(92)
        dialog_layout.addWidget(preview)

        def sync_back_from_full_preview() -> None:
            position = preview.player.position()
            preview.pause_playback()
            preview.player.stop()
            self.seek_to(position)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), dialog, dialog.close)
        dialog.finished.connect(sync_back_from_full_preview)
        dialog.finished.connect(lambda: setattr(self, "_full_preview_dialog", None))
        dialog.resize(1280, 720)
        dialog.showFullScreen()
        preview.toggle_playback()

    def _video_frame_changed(self, frame) -> None:
        if not self._accept_frames and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        if not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self.canvas.set_frame_image(image, has_subtitles=self._source_has_subtitles)

    def _position_changed(self, position: int) -> None:
        if not self.position_slider.isSliderDown():
            with QSignalBlocker(self.position_slider):
                self.position_slider.setValue(position)
        self.canvas.set_position(position / 1000.0)
        self._update_time_label(position, self.player.duration())
        active_index = self._active_cue_index(position / 1000.0)
        if active_index != self._last_active_cue_index:
            self._last_active_cue_index = active_index
            self.activeCueChanged.emit(active_index)

    def _duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, max(0, duration))
        self._update_time_label(self.player.position(), duration)

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState and self._play_requested:
            self._accept_frames = True
        elif state == QMediaPlayer.PlaybackState.StoppedState and self.player.duration() > 0:
            if self.player.position() >= max(0, self.player.duration() - 200):
                self._play_requested = False
                self._accept_frames = False
        self.play_button.setText("Pause" if self._play_requested else "Play")

    def _update_time_label(self, position: int, duration: int) -> None:
        self.time_label.setText(
            f"{format_timecode(position / 1000.0)} / {format_timecode(duration / 1000.0)}"
        )

    def _fit_options_changed(self, *args) -> None:
        del args
        self.canvas.set_fit_options(str(self.fit_mode_combo.currentData()), int(self.fit_margin_spin.value()))

    def _active_cue_index(self, seconds: float) -> int:
        for cue in self._cues:
            if cue.start <= seconds <= cue.end:
                return cue.index
        return -1
