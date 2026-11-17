"""Zone geometry: turn a preset (left/right/center/custom) into a rectangle."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_SCREEN = (3440, 1440)
PRESETS = ("left", "right", "center", "custom")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def offset(self, dx: int, dy: int) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def scaled(self, scale: float) -> "Rect":
        """Physical pixels -> logical (KWin) coordinates for a given display scale."""
        if scale == 1:
            return self
        return Rect(*(round(v / scale) for v in (self.x, self.y, self.w, self.h)))

    def __str__(self) -> str:
        return f"{self.w}x{self.h}+{self.x}+{self.y}"


def parse_size(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", text)
    if not m:
        raise ValueError(f"expected WIDTHxHEIGHT, got {text!r}")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise ValueError(f"size must be positive, got {text!r}")
    return w, h


def parse_point(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*", text)
    if not m:
        raise ValueError(f"expected X,Y, got {text!r}")
    return int(m.group(1)), int(m.group(2))


def parse_rect(text: str) -> Rect:
    """Accept 'X,Y,W,H' or 'WxH+X+Y'."""
    m = re.fullmatch(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*", text)
    if m:
        x, y, w, h = map(int, m.groups())
    else:
        m = re.fullmatch(r"\s*(\d+)[xX](\d+)\+(-?\d+)\+(-?\d+)\s*", text)
        if not m:
            raise ValueError(f"expected X,Y,W,H or WxH+X+Y, got {text!r}")
        w, h, x, y = map(int, m.groups())
    if w <= 0 or h <= 0:
        raise ValueError(f"rect size must be positive, got {text!r}")
    return Rect(x, y, w, h)


def compute_zone(
    preset: str,
    screen: tuple[int, int] = DEFAULT_SCREEN,
    width: int | None = None,
    height: int | None = None,
    rect: Rect | None = None,
) -> Rect:
    """Return the zone rectangle in screen-local physical pixels.

    left/right/center default to half the screen width and full height;
    ``width``/``height`` override that (e.g. ``left --width 2560``).
    """
    sw, sh = screen
    if preset == "custom":
        if rect is None:
            raise ValueError("custom preset needs --rect X,Y,W,H")
        return rect
    if rect is not None:
        raise ValueError("--rect only applies to the custom preset")

    w = width if width is not None else sw // 2
    h = height if height is not None else sh
    if not (0 < w <= sw):
        raise ValueError(f"width {w} does not fit screen width {sw}")
    if not (0 < h <= sh):
        raise ValueError(f"height {h} does not fit screen height {sh}")
    y = (sh - h) // 2

    if preset == "left":
        x = 0
    elif preset == "right":
        x = sw - w
    elif preset == "center":
        x = (sw - w) // 2
    else:
        raise ValueError(f"unknown preset {preset!r} (choose from {', '.join(PRESETS)})")
    return Rect(x, y, w, h)


def fits(rect: Rect, screen: tuple[int, int]) -> bool:
    sw, sh = screen
    return rect.x >= 0 and rect.y >= 0 and rect.x + rect.w <= sw and rect.y + rect.h <= sh


# ---------------------------------------------------------------- size choices (GUI list)

COMMON_SIZES = [
    (3840, 2160), (3440, 1440), (2560, 1600), (2560, 1440), (2560, 1080), (1920, 1200),
    (1920, 1080), (1680, 1050), (1600, 900), (1440, 900), (1366, 768), (1280, 1024),
    (1280, 800), (1280, 720), (1024, 768), (800, 600),
]
_ASPECTS = {"16:9": 16 / 9, "16:10": 16 / 10, "21:9": 64 / 27, "32:9": 32 / 9, "4:3": 4 / 3, "5:4": 5 / 4}


@dataclass(frozen=True)
class SizeChoice:
    w: int
    h: int
    note: str  # e.g. "half width" or "16:9"


def aspect_name(w: int, h: int) -> str:
    r = w / h
    for name, v in _ASPECTS.items():
        if abs(r - v) / v < 0.015:
            return name
    return f"{r:.2f}:1"


def size_choices(screen: tuple[int, int]) -> list[SizeChoice]:
    """Sizes that fit on ``screen``: splits of the screen first, then common resolutions."""
    sw, sh = screen
    splits = [
        ((sw, sh), "full screen"),
        ((round(sw * 2 / 3), sh), "two-thirds width"),
        ((sw // 2, sh), "half width"),
        ((round(sw / 3), sh), "one-third width"),
    ]
    out: list[SizeChoice] = []
    seen: set[tuple[int, int]] = set()
    for (w, h), note in splits:
        if (w, h) not in seen and w > 0:
            seen.add((w, h))
            out.append(SizeChoice(w, h, note))
    common = [s for s in COMMON_SIZES if s[0] <= sw and s[1] <= sh and s not in seen]
    for w, h in sorted(common, key=lambda s: (-s[0] * s[1], -s[0])):
        out.append(SizeChoice(w, h, aspect_name(w, h)))
    return out
