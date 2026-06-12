from __future__ import annotations

import unittest
from pathlib import Path

from core.style_preset import SubtitleStyle, safe_area_insets
from core.subtitle_layout import subtitle_line_positions, subtitle_max_width, wrap_subtitle_text
from core.video_info import VideoInfo


class SafeAreaLayoutTests(unittest.TestCase):
    def test_all_platform_safe_area_limits_width_and_positions(self) -> None:
        info = VideoInfo(Path("vertical.mp4"), 1080, 1920, 10.0, 30.0, "h264")
        style = SubtitleStyle(safe_area_mode="all", max_width_percent=100, font_size=48)

        insets = safe_area_insets(info, style)
        safe_left = insets.left
        safe_right = info.width - insets.right
        max_width = subtitle_max_width(info, style)
        positions = subtitle_line_positions(info, style, 2, renderer="ass")

        self.assertLessEqual(max_width, safe_right - safe_left)
        self.assertGreaterEqual(max_width, round(info.width * 0.80))
        for x, y, an in positions:
            self.assertEqual(an, 5)
            self.assertGreaterEqual(x - max_width / 2, safe_left - 1)
            self.assertLessEqual(x + max_width / 2, safe_right + 1)
            self.assertGreaterEqual(y, insets.top)
            self.assertLessEqual(y, info.height - insets.bottom)

    def test_long_thai_text_is_split_to_safe_width_chunks(self) -> None:
        info = VideoInfo(Path("vertical.mp4"), 1080, 1920, 10.0, 30.0, "h264")
        style = SubtitleStyle(safe_area_mode="all", max_width_percent=100, font_size=48, max_lines=2)
        text = "\u0e01\u0e32\u0e23\u0e17\u0e14\u0e2a\u0e2d\u0e1a" * 18

        lines = wrap_subtitle_text(text, info, style, limit_lines=False)

        self.assertGreater(len(lines), 1)
        self.assertTrue(all(line for line in lines))


if __name__ == "__main__":
    unittest.main()
