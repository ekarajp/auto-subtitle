from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SpeechWord:
    text: str
    start: float
    end: float
