from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.project_config import ProjectConfig, load_project_config, save_project_config
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue


class ProjectConfigTests(unittest.TestCase):
    def test_round_trip_preserves_edited_subtitles_and_state(self) -> None:
        config = ProjectConfig(
            video_path="video.mp4",
            subtitle_path="source.srt",
            output_path="out.mp4",
            style=SubtitleStyle(safe_area_mode="tiktok", font_size=52),
            subtitle_cues=[
                SubtitleCue(1, 0.0, 1.5, "Edited line", {"font_size": 44}),
                SubtitleCue(2, 2.0, 3.5, "Second line"),
            ],
            subtitle_source_format="edited",
            selected_row=1,
            playhead_ms=2200,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            save_project_config(path, config)
            loaded = load_project_config(path)

        self.assertEqual(loaded.style.safe_area_mode, "tiktok")
        self.assertEqual(loaded.style.font_size, 52)
        self.assertEqual(loaded.subtitle_source_format, "edited")
        self.assertEqual(loaded.selected_row, 1)
        self.assertEqual(loaded.playhead_ms, 2200)
        self.assertEqual(len(loaded.subtitle_cues), 2)
        self.assertEqual(loaded.subtitle_cues[0].text, "Edited line")
        self.assertEqual(loaded.subtitle_cues[0].style_overrides["font_size"], 44)


if __name__ == "__main__":
    unittest.main()
