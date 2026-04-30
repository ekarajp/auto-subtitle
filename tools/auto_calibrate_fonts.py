from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.font_calibrator import auto_calibrate_font_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-calibrate preview font metrics against FFmpeg/libass render output.")
    parser.add_argument("families", nargs="+", help="Font families to calibrate, for example: Tahoma 'Noto Sans Thai'")
    parser.add_argument("--write", action="store_true", help="Persist the calibrated profile into config/font_calibration_profiles.json")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    del app

    for family in args.families:
        result = auto_calibrate_font_profile(family, save_result=args.write)
        print(
            json.dumps(
                {
                    "family": result.family,
                    "script": result.script,
                    "score": round(result.score, 3),
                    "sample_count": result.sample_count,
                    "profile": result.best_profile.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
