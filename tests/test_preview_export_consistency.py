from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.preview_renderer import render_accurate_preview_frame
from core.renderer import ensure_ffmpeg
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.video_info import VideoInfo
from ui.preview_widget import VideoSubtitleCanvas


os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")


class PreviewExportConsistencyTests(unittest.TestCase):
    BG_HEX = "#242A31"
    BG_BGRA = np.array([0x31, 0x2A, 0x24, 0xFF], dtype=np.uint8)

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        try:
            cls.ffmpeg = ensure_ffmpeg()
        except Exception as exc:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(str(exc)) from exc
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="preview_export_tests_")
        cls.temp_path = Path(cls.temp_dir.name)
        cls._videos: dict[tuple[int, int], Path] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    @classmethod
    def _video_info(cls, width: int, height: int) -> VideoInfo:
        key = (width, height)
        if key not in cls._videos:
            path = cls.temp_path / f"blank_{width}x{height}.mp4"
            subprocess.run(
                [
                    cls.ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={cls.BG_HEX}:s={width}x{height}:d=2",
                    "-pix_fmt",
                    "yuv420p",
                    str(path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cls._videos[key] = path
        return VideoInfo(cls._videos[key], width, height, 2.0, 25.0, "h264")

    def _bbox(self, image: QImage) -> tuple[int, int, int, int]:
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
        buffer = np.frombuffer(image.bits(), np.uint8).reshape((image.height(), image.width(), 4))
        diff = np.any(np.abs(buffer.astype(np.int16) - self.BG_BGRA.astype(np.int16)) > 20, axis=2)
        ys, xs = np.where(diff)
        self.assertGreater(len(xs), 0, "subtitle pixels were not rendered")
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    def _bbox_center(self, bbox: tuple[int, int, int, int]) -> tuple[float, float]:
        return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)

    def _render_accurate_bbox(
        self,
        *,
        info: VideoInfo,
        cue: SubtitleCue,
        style: SubtitleStyle,
    ) -> tuple[int, int, int, int]:
        image = QImage.fromData(
            render_accurate_preview_frame(
                video_info=info,
                cues=[cue],
                style=style,
                position_seconds=min(cue.start + 0.1, cue.end - 0.01),
            )
        )
        return self._bbox(image)

    def _render_preview_bbox(
        self,
        *,
        info: VideoInfo,
        cue: SubtitleCue,
        style: SubtitleStyle,
        canvas_size: tuple[int, int] | None = None,
    ) -> tuple[tuple[int, int, int, int], QRect]:
        canvas_width, canvas_height = canvas_size or (info.width, info.height)
        canvas = VideoSubtitleCanvas()
        canvas.resize(canvas_width, canvas_height)
        canvas.set_video_info(info)
        canvas.set_style(style)
        canvas.set_cues([cue])

        image = QImage(canvas_width, canvas_height, QImage.Format.Format_ARGB32)
        image.fill(QColor(self.BG_HEX))
        painter = QPainter(image)
        video_rect = canvas._video_rect()
        canvas._draw_subtitle(painter, video_rect, cue)
        painter.end()
        return self._bbox(image), video_rect

    def _assert_centers_close(
        self,
        preview_bbox: tuple[int, int, int, int],
        accurate_bbox: tuple[int, int, int, int],
        *,
        tolerance: float = 18.0,
    ) -> None:
        preview_center = self._bbox_center(preview_bbox)
        accurate_center = self._bbox_center(accurate_bbox)
        self.assertLessEqual(abs(preview_center[0] - accurate_center[0]), tolerance)
        self.assertLessEqual(abs(preview_center[1] - accurate_center[1]), tolerance)

    def test_bottom_center_matches_export_position(self) -> None:
        info = self._video_info(1280, 720)
        cue = SubtitleCue(1, 0.0, 1.5, "Hello world")
        style = SubtitleStyle(
            font_family="Arial",
            font_size=48,
            alignment="bottom_center",
            stroke_enabled=True,
            stroke_width=3.0,
            shadow_enabled=False,
        )

        preview_bbox, _ = self._render_preview_bbox(info=info, cue=cue, style=style)
        accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)

        self._assert_centers_close(preview_bbox, accurate_bbox)
        self.assertLessEqual(abs((preview_bbox[2] - preview_bbox[0]) - (accurate_bbox[2] - accurate_bbox[0])), 52)

    def test_cue_font_size_override_matches_export_size(self) -> None:
        info = self._video_info(1280, 720)
        cue = SubtitleCue(
            1,
            0.0,
            1.5,
            "Manual size override",
            style_overrides={"font_size": 72},
        )
        style = SubtitleStyle(
            font_family="Arial",
            font_size=36,
            alignment="bottom_center",
            stroke_enabled=True,
            stroke_width=3.0,
            shadow_enabled=False,
        )

        preview_bbox, _ = self._render_preview_bbox(info=info, cue=cue, style=style)
        accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)

        self._assert_centers_close(preview_bbox, accurate_bbox, tolerance=24.0)
        self.assertLessEqual(abs((preview_bbox[2] - preview_bbox[0]) - (accurate_bbox[2] - accurate_bbox[0])), 100)
        self.assertLessEqual(abs((preview_bbox[3] - preview_bbox[1]) - (accurate_bbox[3] - accurate_bbox[1])), 40)

    def test_left_and_right_alignment_preserve_expected_edges(self) -> None:
        info = self._video_info(1280, 720)
        cue = SubtitleCue(1, 0.0, 1.5, "Hello world")

        for alignment, edge_index in (("bottom_left", 0), ("bottom_right", 2)):
            with self.subTest(alignment=alignment):
                style = SubtitleStyle(
                    font_family="Arial",
                    font_size=48,
                    alignment=alignment,
                    stroke_enabled=True,
                    stroke_width=3.0,
                    shadow_enabled=False,
                )
                preview_bbox, _ = self._render_preview_bbox(info=info, cue=cue, style=style)
                accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)
                self.assertLessEqual(
                    abs(self._bbox_center(preview_bbox)[1] - self._bbox_center(accurate_bbox)[1]),
                    18.0,
                )
                self.assertLessEqual(abs(preview_bbox[edge_index] - accurate_bbox[edge_index]), 8)

    def test_multiline_center_alignment_matches_export(self) -> None:
        info = self._video_info(1280, 720)
        cue = SubtitleCue(1, 0.0, 1.5, "Line one\nLine two")
        style = SubtitleStyle(
            font_family="Arial",
            font_size=48,
            alignment="center",
            stroke_enabled=True,
            stroke_width=3.0,
            shadow_enabled=False,
        )

        preview_bbox, _ = self._render_preview_bbox(info=info, cue=cue, style=style)
        accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)

        self._assert_centers_close(preview_bbox, accurate_bbox)
        self.assertLessEqual(abs((preview_bbox[2] - preview_bbox[0]) - (accurate_bbox[2] - accurate_bbox[0])), 52)

    def test_multiline_custom_line_spacing_matches_export(self) -> None:
        info = self._video_info(1280, 720)
        cue = SubtitleCue(1, 0.0, 1.5, "Line one\nLine two")
        style = SubtitleStyle(
            font_family="Arial",
            font_size=48,
            alignment="bottom_center",
            line_spacing=-12,
            stroke_enabled=True,
            stroke_width=3.0,
            shadow_enabled=False,
        )

        preview_bbox, _ = self._render_preview_bbox(info=info, cue=cue, style=style)
        accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)

        self._assert_centers_close(preview_bbox, accurate_bbox, tolerance=18.0)
        self.assertLessEqual(abs((preview_bbox[3] - preview_bbox[1]) - (accurate_bbox[3] - accurate_bbox[1])), 32)

    def test_portrait_safe_margin_stays_consistent(self) -> None:
        info = self._video_info(720, 1280)
        cue = SubtitleCue(1, 0.0, 1.5, "Portrait sample subtitle")
        style = SubtitleStyle(
            font_family="Arial",
            font_size=48,
            alignment="bottom_center",
            stroke_enabled=True,
            stroke_width=3.0,
            shadow_enabled=False,
        )

        preview_bbox, _ = self._render_preview_bbox(info=info, cue=cue, style=style)
        accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)

        self._assert_centers_close(preview_bbox, accurate_bbox)
        preview_bottom_margin = info.height - preview_bbox[3]
        accurate_bottom_margin = info.height - accurate_bbox[3]
        self.assertLessEqual(abs(preview_bottom_margin - accurate_bottom_margin), 16)

    def test_preview_canvas_resize_does_not_change_source_space_position(self) -> None:
        info = self._video_info(1280, 720)
        cue = SubtitleCue(1, 0.0, 1.5, "Hello world")
        style = SubtitleStyle(
            font_family="Arial",
            font_size=48,
            alignment="bottom_center",
            stroke_enabled=True,
            stroke_width=3.0,
            shadow_enabled=False,
        )

        accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)
        accurate_center = self._bbox_center(accurate_bbox)
        preview_bbox, video_rect = self._render_preview_bbox(
            info=info,
            cue=cue,
            style=style,
            canvas_size=(1000, 900),
        )
        preview_center = self._bbox_center(preview_bbox)
        scale_x = video_rect.width() / info.width
        scale_y = video_rect.height() / info.height
        mapped_center = (
            (preview_center[0] - video_rect.left()) / scale_x,
            (preview_center[1] - video_rect.top()) / scale_y,
        )

        self.assertLessEqual(abs(mapped_center[0] - accurate_center[0]), 2.5)
        self.assertLessEqual(abs(mapped_center[1] - accurate_center[1]), 18.0)

    def test_thai_fonts_stay_close_to_accurate_preview(self) -> None:
        info = self._video_info(1080, 1920)
        cue = SubtitleCue(
            1,
            0.0,
            2.0,
            (
                "\u0e2a\u0e34\u0e48\u0e07\u0e21\u0e35\u0e0a\u0e35\u0e27\u0e34\u0e15"
                "\u0e17\u0e38\u0e01\u0e0a\u0e19\u0e34\u0e14\u0e1a\u0e19\u0e42\u0e25"
                "\u0e01\u0e44\u0e21\u0e48\u0e44\u0e14\u0e49\u0e16\u0e39\u0e01\n"
                "\u0e2d\u0e2d\u0e01\u0e41\u0e1a\u0e1a\u0e21\u0e32"
            ),
        )

        for family in ("Tahoma", "Noto Sans Thai", "Leelawadee UI", "Arial", "Segoe UI"):
            with self.subTest(font_family=family):
                style = SubtitleStyle(
                    font_family=family,
                    font_size=48,
                    alignment="bottom_center",
                    stroke_enabled=True,
                    stroke_width=3.0,
                    shadow_enabled=True,
                    shadow_offset=2.0,
                )
                preview_bbox, _ = self._render_preview_bbox(info=info, cue=cue, style=style)
                accurate_bbox = self._render_accurate_bbox(info=info, cue=cue, style=style)

                preview_center = self._bbox_center(preview_bbox)
                accurate_center = self._bbox_center(accurate_bbox)
                preview_width = preview_bbox[2] - preview_bbox[0]
                accurate_width = accurate_bbox[2] - accurate_bbox[0]
                preview_height = preview_bbox[3] - preview_bbox[1]
                accurate_height = accurate_bbox[3] - accurate_bbox[1]

                self.assertLessEqual(abs(preview_center[0] - accurate_center[0]), 2.0)
                self.assertLessEqual(abs(preview_center[1] - accurate_center[1]), 20.0)
                self.assertLessEqual(abs(preview_width - accurate_width), 220)
                self.assertLessEqual(abs(preview_height - accurate_height), 60)

    def test_thai_cue_in_mixed_language_document_uses_thai_calibration(self) -> None:
        info = self._video_info(1080, 1920)
        thai_cue = SubtitleCue(
            1,
            0.0,
            2.0,
            "\u0e17\u0e14\u0e2a\u0e2d\u0e1a\u0e02\u0e49\u0e2d\u0e04\u0e27\u0e32\u0e21\u0e44\u0e17\u0e22\u0e1b\u0e19\u0e01\u0e31\u0e1a\u0e40\u0e2d\u0e01\u0e2a\u0e32\u0e23\u0e20\u0e32\u0e29\u0e32\u0e2d\u0e31\u0e07\u0e01\u0e24\u0e29",
        )
        english_cue = SubtitleCue(2, 2.2, 3.5, "English calibration sample")
        style = SubtitleStyle(
            font_family="Tahoma",
            font_size=48,
            alignment="bottom_center",
            stroke_enabled=True,
            stroke_width=3.0,
            shadow_enabled=True,
            shadow_offset=2.0,
        )

        canvas = VideoSubtitleCanvas()
        canvas.resize(info.width, info.height)
        canvas.set_video_info(info)
        canvas.set_style(style)
        canvas.set_cues([thai_cue, english_cue])
        image = QImage(info.width, info.height, QImage.Format.Format_ARGB32)
        image.fill(QColor(self.BG_HEX))
        painter = QPainter(image)
        canvas._draw_subtitle(painter, canvas._video_rect(), thai_cue)
        painter.end()
        preview_bbox = self._bbox(image)
        accurate_bbox = self._bbox(
            QImage.fromData(
                render_accurate_preview_frame(
                    video_info=info,
                    cues=[thai_cue, english_cue],
                    style=style,
                    position_seconds=0.5,
                )
            )
        )

        self._assert_centers_close(preview_bbox, accurate_bbox, tolerance=10.0)
        self.assertLessEqual(abs((preview_bbox[3] - preview_bbox[1]) - (accurate_bbox[3] - accurate_bbox[1])), 40)


if __name__ == "__main__":
    unittest.main()
