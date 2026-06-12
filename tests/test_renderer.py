from __future__ import annotations

import unittest
from pathlib import Path

from core.renderer import _build_render_command


class RendererCommandTests(unittest.TestCase):
    def test_render_command_excludes_input_subtitle_streams(self) -> None:
        command = _build_render_command(
            ffmpeg="ffmpeg",
            input_path=Path("input.mp4"),
            filter_arg="ass='subtitle.ass'",
            output_path=Path("output.mp4"),
        )

        self.assertIn("-sn", command)
        self.assertEqual(command[command.index("-map") + 1], "0:v:0")
        self.assertIn("0:a?", command)


if __name__ == "__main__":
    unittest.main()
