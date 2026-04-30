from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from core.font_calibrator import auto_calibrate_font_profiles
from core.font_calibration import save_font_calibration_profiles
from core.style_preset import SubtitleStyle


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate Qt preview font profiles against FFmpeg/libass.")
    parser.add_argument("--families", nargs="*", default=["Prompt"], help="Font families to calibrate.")
    parser.add_argument("--all", action="store_true", help="Calibrate every installed font family. This can take a long time.")
    parser.add_argument("--scripts", nargs="*", default=["latin", "thai"], help="Script groups to calibrate.")
    parser.add_argument("--font-size", type=int, default=48, help="Base source font size used for calibration.")
    parser.add_argument("--stroke-width", type=float, default=3.0, help="Stroke width used for the style-specific key.")
    parser.add_argument("--no-shadow", action="store_true", help="Disable shadow in the calibrated style key.")
    parser.add_argument("--save", action="store_true", help="Write profiles to config/font_calibration_profiles.json.")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    del app

    families = list(args.families)
    if args.all:
        families = sorted(QFontDatabase.families(), key=str.casefold)

    style = SubtitleStyle(
        font_size=max(1, args.font_size),
        stroke_enabled=args.stroke_width > 0,
        stroke_width=max(0.0, args.stroke_width),
        shadow_enabled=not args.no_shadow,
        shadow_offset=0.0 if args.no_shadow else 2.0,
    )

    all_profiles = []
    report = []
    for family in families:
        results = auto_calibrate_font_profiles(family, scripts=list(args.scripts), base_style=style, save_result=False)
        for result in results:
            all_profiles.append(result.best_profile)
            report.append(
                {
                    "family": result.family,
                    "script": result.script,
                    "style_key": result.style_key,
                    "score": round(result.score, 3),
                    "sample_count": result.sample_count,
                    "profile": result.best_profile.to_dict(),
                }
            )

    if args.save and all_profiles:
        save_font_calibration_profiles(all_profiles)

    print(json.dumps({"saved": bool(args.save and all_profiles), "results": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
