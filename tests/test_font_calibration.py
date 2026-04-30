from __future__ import annotations

import os
import unittest

from PySide6.QtWidgets import QApplication

from core.font_calibration import FontCalibrationProfile, detect_script_category, resolve_font_calibration, temporary_profile_overrides
from core.font_diagnostics import collect_font_measurement_diagnostics
from core.style_preset import SubtitleStyle
from core.subtitle_layout import style_calibration_key


os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")


class FontCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_script_detection(self) -> None:
        self.assertEqual(detect_script_category("Hello world"), "latin")
        self.assertEqual(detect_script_category("\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35"), "thai")
        self.assertEqual(detect_script_category("\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35!?"), "thai")
        self.assertEqual(detect_script_category("\u6f22\u5b57"), "cjk")
        self.assertEqual(detect_script_category("\u0627\u0644\u0639\u0631\u0628\u064a\u0629"), "arabic")
        self.assertEqual(detect_script_category("\u0939\u093f\u0928\u094d\u0926\u0940"), "devanagari")

    def test_family_specific_profiles_override_generic_script_profile(self) -> None:
        default_profile = resolve_font_calibration("Tahoma", "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35")
        self.assertAlmostEqual(default_profile.size_scale, 0.84, places=2)
        override = FontCalibrationProfile(family="Tahoma", script="thai", size_scale=0.91)
        with temporary_profile_overrides([override]):
            profile = resolve_font_calibration("Tahoma", "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35")
            self.assertAlmostEqual(profile.size_scale, 0.91, places=2)
        restored = resolve_font_calibration("Tahoma", "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35")
        self.assertAlmostEqual(restored.size_scale, 0.84, places=2)

    def test_style_specific_profile_overrides_generic_profile(self) -> None:
        style = SubtitleStyle(stroke_enabled=True, stroke_width=4.0, shadow_enabled=False)
        key = style_calibration_key(style)
        generic = FontCalibrationProfile(family="Prompt", script="thai", size_scale=0.66)
        specific = FontCalibrationProfile(family="Prompt", script="thai", style_key=key, size_scale=0.61)
        with temporary_profile_overrides([generic, specific]):
            profile = resolve_font_calibration("Prompt", "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35", key)
            self.assertAlmostEqual(profile.size_scale, 0.61, places=2)
            fallback = resolve_font_calibration("Prompt", "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35")
            self.assertAlmostEqual(fallback.size_scale, 0.66, places=2)

    def test_prompt_has_font_specific_thai_and_latin_profiles(self) -> None:
        thai = resolve_font_calibration("Prompt", "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35")
        latin = resolve_font_calibration("Prompt", "Hello world")
        self.assertAlmostEqual(thai.size_scale, 0.66, places=2)
        self.assertAlmostEqual(thai.path_scale_y, 1.0, places=2)
        self.assertAlmostEqual(latin.size_scale, 0.68, places=2)

    def test_prompt_weight_variants_fall_back_to_prompt_base_profile(self) -> None:
        for family in ("Prompt Medium", "Prompt SemiBold", "Prompt Black"):
            with self.subTest(font_family=family):
                thai = resolve_font_calibration(family, "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35")
                latin = resolve_font_calibration(family, "Hello world")
                self.assertAlmostEqual(thai.size_scale, 0.66, places=2)
                self.assertAlmostEqual(latin.size_scale, 0.68, places=2)

    def test_mixed_thai_latin_prompt_uses_mixed_profile(self) -> None:
        sample = "\u0e17\u0e14\u0e2a\u0e2d\u0e1a Prompt Medium 123 \u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22"
        profile = resolve_font_calibration("Prompt Medium", sample)
        self.assertEqual(profile.script, "mixed")
        self.assertAlmostEqual(profile.size_scale, 0.66, places=2)
        self.assertAlmostEqual(profile.path_scale_y, 1.0, places=2)

    def test_diagnostics_report_calibration_and_metrics(self) -> None:
        style = SubtitleStyle(font_family="Tahoma", font_size=48)
        diagnostics = collect_font_measurement_diagnostics(
            style,
            "\u0e2a\u0e34\u0e48\u0e07\u0e21\u0e35\u0e0a\u0e35\u0e27\u0e34\u0e15",
        )
        payload = diagnostics.to_dict()
        self.assertIn("calibration", payload)
        self.assertEqual(payload["script"], "thai")
        self.assertGreater(payload["preview_font_size"], 0)
        self.assertGreater(payload["ass_font_size"], 0)
        self.assertIn("profile", payload["calibration"])
        self.assertIn("style_key", payload)


if __name__ == "__main__":
    unittest.main()
