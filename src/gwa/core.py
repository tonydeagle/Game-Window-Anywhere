"""Logic shared by the CLI and the GUI. Raises ValueError instead of exiting."""

from __future__ import annotations

import shlex
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from . import gamescope, kwinrules
from .monitors import Live, Monitor, insets
from .presets import Settings
from .zones import Rect, compute_zone, fits


@dataclass(frozen=True)
class Plan:
    zone: Rect             # screen-local, physical pixels
    kwin_rect: Rect        # KWin global layout, logical pixels
    gamescope_args: list[str]
    warnings: tuple[str, ...] = ()
    settings: Settings | None = None     # settings after monitor detection was applied
    monitor: Monitor | None = None
    insets: tuple[int, int, int, int] = (0, 0, 0, 0)  # panel space kept free (fit), physical px


def needs_live(s: Settings) -> bool:
    """Whether planning these settings benefits from detecting monitors/panels."""
    return bool(s.monitor) or s.taskbar in ("fit", "autohide")


def effective(s: Settings, live: Live | None) -> tuple[Settings, Monitor | None, list[str]]:
    """Replace screen/origin/scale with the live monitor's values when the preset follows one."""
    if not s.monitor:
        return s, None, []
    if live is None or not live.monitors:
        why = live.monitor_error if live and live.monitor_error else "monitor detection unavailable"
        return s, None, [f"{why}; using the stored {s.screen[0]}x{s.screen[1]} screen"]
    m = live.find(s.monitor)
    if m is None:
        names = ", ".join(x.name for x in live.monitors)
        return s, None, [f"monitor '{s.monitor}' not connected (found: {names}); "
                         f"using the stored {s.screen[0]}x{s.screen[1]} screen"]
    return replace(s, screen=m.size, origin=(m.x, m.y), scale=m.scale), m, []


def plan(s: Settings, live: Live | None = None) -> Plan:
    """Work out where the window goes and how gamescope is called for these settings."""
    eff, monitor, warnings = effective(s, live)
    if eff.scale <= 0:
        raise ValueError("scale must be positive")

    ins = (0, 0, 0, 0)
    if eff.taskbar == "fit":
        if live is None or live.panel_error:
            warnings.append("couldn't detect the taskbar"
                            + (f" ({live.panel_error})" if live and live.panel_error else "")
                            + "; zone not shrunk")
        elif eff.zone == "custom":
            warnings.append("'fit above taskbar' doesn't apply to a custom zone")
        else:
            ins = insets(live.panels_on(monitor), eff.scale)

    l, t, r, b = ins
    area = (eff.screen[0] - l - r, eff.screen[1] - t - b)
    try:
        zone = compute_zone(eff.zone, area, eff.width, eff.height, eff.rect).offset(l, t) \
            if eff.zone != "custom" else compute_zone("custom", eff.screen, rect=eff.rect)
    except ValueError as e:
        if any(ins):
            raise ValueError(f"{e} (the taskbar takes {max(ins)} px; "
                             f"usable area is {area[0]}x{area[1]})") from None
        raise
    if eff.zone == "custom" and not fits(zone, eff.screen):
        warnings.append(f"zone {zone} extends past the {eff.screen[0]}x{eff.screen[1]} screen")
    try:
        extra = shlex.split(eff.gamescope_args)
    except ValueError as e:
        raise ValueError(f"gamescope_args: {e}") from None
    return Plan(
        zone=zone,
        kwin_rect=zone.scaled(eff.scale).offset(*eff.origin),
        gamescope_args=gamescope.gamescope_args(zone.w, zone.h, eff.render, extra),
        warnings=tuple(warnings),
        settings=eff,
        monitor=monitor,
        insets=ins,
    )


def write_rule(s: Settings, label: str, kwin_rect: Rect, path: Path) -> tuple[Path | None, list[str]]:
    """Write the managed KWin rule. Returns (backup path, descriptions of conflicting rules)."""
    values = kwinrules.build_rule(kwin_rect, s.wmclass, f"{label} {kwin_rect}",
                                  above_panels=s.taskbar == "cover")
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
