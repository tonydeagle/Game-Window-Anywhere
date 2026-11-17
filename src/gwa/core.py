"""Logic shared by the CLI and the GUI. Raises ValueError instead of exiting."""

from __future__ import annotations

import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import gamescope, kwinrules
from .presets import Settings
from .zones import Rect, compute_zone, fits


@dataclass(frozen=True)
class Plan:
    zone: Rect             # screen-local, physical pixels
    kwin_rect: Rect        # KWin global layout, logical pixels
    gamescope_args: list[str]
    warnings: tuple[str, ...] = ()


def plan(s: Settings) -> Plan:
    """Work out where the window goes and how gamescope is called for these settings."""
    zone = compute_zone(s.zone, s.screen, s.width, s.height, s.rect)
    if s.scale <= 0:
        raise ValueError("scale must be positive")
    warnings = []
    if s.zone == "custom" and not fits(zone, s.screen):
        warnings.append(f"zone {zone} extends past the {s.screen[0]}x{s.screen[1]} screen")
    try:
        extra = shlex.split(s.gamescope_args)
    except ValueError as e:
        raise ValueError(f"gamescope_args: {e}") from None
    return Plan(
        zone=zone,
        kwin_rect=zone.scaled(s.scale).offset(*s.origin),
        gamescope_args=gamescope.gamescope_args(zone.w, zone.h, s.render, extra),
        warnings=tuple(warnings),
    )


def write_rule(s: Settings, label: str, kwin_rect: Rect, path: Path) -> tuple[Path | None, list[str]]:
    """Write the managed KWin rule. Returns (backup path, descriptions of conflicting rules)."""
    values = kwinrules.build_rule(kwin_rect, s.wmclass, f"{label} {kwin_rect}")
    cfg = kwinrules.KConfig.load(path)
    conflicts = kwinrules.other_gamescope_rules(cfg, s.wmclass)
    kwinrules.upsert_rule(cfg, values)
    return kwinrules.save(cfg, path), conflicts


def gwa_executable() -> str:
    """Absolute path to the gwa command, for launch options that call back into it."""
    argv0 = Path(sys.argv[0])
    if argv0.name == "gwa" and argv0.exists():
        return str(argv0.resolve())
    checkout_shim = Path(__file__).resolve().parents[2] / "gwa"  # running from a git checkout
    if checkout_shim.is_file():
        return str(checkout_shim)
    return shutil.which("gwa") or "gwa"


def preset_launch_options(name: str, gwa: str | None = None) -> tuple[str, str, str]:
    """(Steam launch option, Heroic wrapper executable, Heroic wrapper arguments) for a preset."""
    gwa = gwa or gwa_executable()
    return f"{shlex.join([gwa, 'run', name])} -- %command%", gwa, f"run {name} --"
