from __future__ import annotations

import unittest
from pathlib import Path

from core.subtitle_arranger import arrange_cues_for_readability
from core.subtitle_layout import wrap_subtitle_text
from core.style_preset import SubtitleStyle
from core.subtitle_models import SubtitleCue
from core.text_normalizer import compact_text_identity
from core.thai_text_processor import likely_broken_thai_fragment
from core.video_info import VideoInfo


class SubtitleArrangerTests(unittest.TestCase):
    def test_auto_arrange_reflows_odd_manual_breaks_without_changing_text(self) -> None:
        info = VideoInfo(Path("sample.mp4"), 1080, 1920, 12.0, 30.0, "h264")
        style = SubtitleStyle(font_family="Tahoma", font_size=48, max_lines=2, max_width_percent=88)
        text = (
            "ทำไมหมาถึงกลายเป็นสัตว์เลี้ยง\n\n"
            "หรืออาจจะเรียกได้ว่าเป็นเพื่อนที่ดีที่สุด\n"
            "ของมนุษย์และอยู่ร่วมกับมนุษย์มาอย่างยาวนาน"
        )
        cue = SubtitleCue(1, 0.0, 8.0, text)

        arranged = arrange_cues_for_readability([cue], video_info=info, style=style, max_lines=2)

        self.assertGreaterEqual(len(arranged), 2)
        self.assertEqual(compact_text_identity("".join(cue.text for cue in arranged)), compact_text_identity(text))
        for arranged_cue in arranged:
            self.assertNotIn("\n\n", arranged_cue.text)
            self.assertFalse(likely_broken_thai_fragment(arranged_cue.text))
            self.assertLessEqual(len(wrap_subtitle_text(arranged_cue.text, info, style, limit_lines=False)), 2)

    def test_auto_arrange_avoids_tiny_orphan_final_cue_when_it_can_merge(self) -> None:
        info = VideoInfo(Path("sample.mp4"), 1280, 720, 8.0, 30.0, "h264")
        style = SubtitleStyle(font_family="Tahoma", font_size=42, max_lines=2, max_width_percent=90)
        text = "This is a readable sentence that should stay balanced instead of leaving ok alone"
        cue = SubtitleCue(1, 0.0, 6.0, text)

        arranged = arrange_cues_for_readability([cue], video_info=info, style=style, max_lines=2)

        self.assertEqual(compact_text_identity("".join(cue.text for cue in arranged)), compact_text_identity(text))
        self.assertGreaterEqual(min(len(cue.text.replace("\n", " ").split()) for cue in arranged), 2)


if __name__ == "__main__":
    unittest.main()
