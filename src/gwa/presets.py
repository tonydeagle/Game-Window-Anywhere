"""Settings model and named, per-game presets stored in a TOML file.

Example ``~/.config/game-window-anywhere/presets.toml``::

    [rocketleague]
    zone = "right"
    width = 2560
    gamescope_args = "-r 144"

    [spire]
    zone = "left"
    command = ["/home/me/Games/SlayTheSpire/SlayTheSpire"]

Only values that differ from the defaults are stored.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

from .zones import DEFAULT_SCREEN, PRESETS, Rect, parse_point, parse_rect, parse_size

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

# leave: do nothing; fit: shrink the zone to stay clear of always-visible panels;
# autohide: auto-hide panels while the game runs; cover: game window stacks above panels.
TASKBAR_MODES = ("leave", "fit", "autohide", "cover")


@dataclass(frozen=True)
class Settings:
    zone: str = "left"
    screen: tuple[int, int] = DEFAULT_SCREEN
    width: int | None = None
    height: int | None = None
    rect: Rect | None = None
    origin: tuple[int, int] = (0, 0)
    scale: float = 1.0
    render: tuple[int, int] | None = None
    gamescope_args: str = ""
    wmclass: str = "gamescope"
    command: tuple[str, ...] = ()
    # "" = use screen/origin/scale as stored; "primary" or an output name (e.g. "DP-1")
    # = read them from that monitor at launch, keeping the stored values as a fallback.
    monitor: str = ""
    taskbar: str = "leave"

    def merged(self, **overrides) -> "Settings":
        """Return a copy with every non-None override applied."""
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


DEFAULTS = Settings()
FIELD_NAMES = tuple(f.name for f in fields(Settings))


# ---------------------------------------------------------------- (de)serialise

def _size_str(v: tuple[int, int]) -> str:
    return f"{v[0]}x{v[1]}"


def to_table(s: Settings) -> dict[str, object]:
    """Settings -> TOML-friendly dict holding only non-default values (zone always kept)."""
    out: dict[str, object] = {"zone": s.zone}
    for name in FIELD_NAMES[1:]:
        v = getattr(s, name)
        if v == getattr(DEFAULTS, name):
            continue
        if name in ("screen", "render"):
            v = _size_str(v)
        elif name == "origin":
            v = f"{v[0]},{v[1]}"
        elif name == "rect":
            v = f"{v.x},{v.y},{v.w},{v.h}"
        elif name == "command":
            v = list(v)
        out[name] = v
    return out


def from_table(name: str, table: dict) -> Settings:
    """TOML table -> Settings, with errors that name the preset and key."""
    def bad(key, msg):
        return ValueError(f"preset '{name}': {key}: {msg}")

    unknown = set(table) - set(FIELD_NAMES)
    if unknown:
        raise bad(", ".join(sorted(unknown)), f"unknown key (allowed: {', '.join(FIELD_NAMES)})")

    kw: dict[str, object] = {}
    for key, v in table.items():
        try:
            if key == "zone":
                if v not in PRESETS:
                    raise ValueError(f"must be one of {', '.join(PRESETS)}")
            elif key in ("screen", "render"):
                v = parse_size(_need(v, str))
            elif key == "origin":
                v = parse_point(_need(v, str))
            elif key == "rect":
                v = parse_rect(_need(v, str))
            elif key in ("width", "height"):
                v = _need(v, int)
            elif key == "scale":
                v = float(_need(v, (int, float)))
            elif key == "monitor":
                v = _need(v, str)
            elif key == "taskbar":
                if v not in TASKBAR_MODES:
                    raise ValueError(f"must be one of {', '.join(TASKBAR_MODES)}")
            elif key in ("gamescope_args", "wmclass"):
                v = _need(v, str)
            elif key == "command":
                if isinstance(v, str):
                    raise ValueError('must be a list, e.g. ["/path/to/game", "--arg"]')
                v = tuple(_need(x, str) for x in _need(v, list))
        except ValueError as e:
            raise bad(key, str(e)) from None
        kw[key] = v
    return Settings(**kw)


def _need(v, types):
    if isinstance(v, bool) or not isinstance(v, types):
        names = types.__name__ if isinstance(types, type) else "/".join(t.__name__ for t in types)
        raise ValueError(f"expected {names}, got {v!r}")
    return v


def _toml_value(v: object) -> str:
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON string escapes are valid TOML
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"can't write {type(v).__name__} to TOML")


def dumps(presets: dict[str, Settings]) -> str:
    lines = [
        "# Game Window Anywhere presets — written by `gwa save`.",
        "# Safe to edit by hand, but comments are not kept when gwa rewrites this file.",
    ]
    for name in sorted(presets):
        lines += ["", f"[{name}]"]
        lines += [f"{k} = {_toml_value(v)}" for k, v in to_table(presets[name]).items()]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- file store

def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "game-window-anywhere" / "presets.toml"


def validate_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"preset name {name!r}: use letters, digits, '-' or '_' (max 64, "
                         "starting with a letter or digit)")
    if name in PRESETS:
        raise ValueError(f"preset name {name!r} is a built-in zone; pick another name")


def load(path: Path) -> dict[str, Settings]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: {e}") from None
    out = {}
    for name, table in data.items():
        if not isinstance(table, dict):
            raise ValueError(f"{path}: '{name}' should be a [section], not a plain value")
        out[name] = from_table(name, table)
    return out


def save(presets: dict[str, Settings], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(presets), encoding="utf-8")
    os.replace(tmp, path)
