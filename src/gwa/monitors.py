"""Detect monitors (kscreen-doctor) and Plasma panels (plasmashell scripting)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

# libkscreen Output::Rotation bit flags: None=1, Left=2, Inverted=4, Right=8.
_QUARTER_TURNS = {2, 8}


@dataclass(frozen=True)
class Monitor:
    name: str               # e.g. "DP-1"
    width: int              # physical pixels of the current mode, after rotation
    height: int
    x: int = 0              # top-left in KWin's global layout (logical pixels)
    y: int = 0
    scale: float = 1.0
    refresh: float = 0.0    # Hz
    primary: bool = False

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def logical(self) -> tuple[int, int, int, int]:
        return self.x, self.y, round(self.width / self.scale), round(self.height / self.scale)

    def label(self) -> str:
        hz = f" · {round(self.refresh)} Hz" if self.refresh else ""
        scale = f" · {self.scale:g}×" if self.scale != 1 else ""
        return f"{self.name} · {self.width} × {self.height}{hz}{scale}"


@dataclass(frozen=True)
class Panel:
    index: int              # position in plasmashell's panels() list
    location: str           # "top" | "bottom" | "left" | "right" | "floating" | ...
    thickness: int          # logical pixels
    hiding: str             # "none" (always visible) | "autohide" | "dodgewindows"
    screen: int = -1
    geometry: tuple[int, int, int, int] | None = None  # screen rect in logical px, if known

    @property
    def always_visible(self) -> bool:
        return self.hiding == "none"


@dataclass
class Live:
    """What we could detect right now. Empty lists + an error mean 'not available'."""
    monitors: list[Monitor] = field(default_factory=list)
    panels: list[Panel] = field(default_factory=list)
    monitor_error: str = ""
    panel_error: str = ""

    def find(self, wanted: str) -> Monitor | None:
        """Look up 'primary' or an output name."""
        if not wanted or not self.monitors:
            return None
        if wanted == "primary":
            return next((m for m in self.monitors if m.primary), self.monitors[0])
        return next((m for m in self.monitors if m.name == wanted), None)

    def panels_on(self, monitor: Monitor | None) -> list[Panel]:
        """Panels on a monitor. With one monitor (or unknown geometry) that's every panel."""
        if monitor is None or len(self.monitors) <= 1:
            return list(self.panels)
        out = []
        for p in self.panels:
            if p.geometry is not None:
                if p.geometry == monitor.logical:
                    out.append(p)
            elif self.monitors.index(monitor) == max(p.screen, 0):
                out.append(p)  # best effort: plasmashell screen index ~ kscreen order
        return out


# ---------------------------------------------------------------- monitors

def parse_kscreen(text: str) -> list[Monitor]:
    data = json.loads(text)
    monitors = []
    for o in data.get("outputs", []):
        if not o.get("connected", True) or o.get("enabled", True) is False:
            continue
        mode = next((m for m in o.get("modes", []) if str(m.get("id")) == str(o.get("currentModeId"))), None)
        if mode:
            w, h = int(mode["size"]["width"]), int(mode["size"]["height"])
            refresh = float(mode.get("refreshRate", 0) or 0)
        else:  # no current mode listed: fall back to the output's own size
            w, h = int(o["size"]["width"]), int(o["size"]["height"])
            refresh = 0.0
        if int(o.get("rotation", 1)) in _QUARTER_TURNS:
            w, h = h, w
        pos = o.get("pos", {})
        monitors.append(Monitor(
            name=str(o.get("name", f"output-{o.get('id')}")), width=w, height=h,
            x=int(pos.get("x", 0)), y=int(pos.get("y", 0)),
            scale=float(o.get("scale", 1) or 1), refresh=refresh,
            primary=int(o.get("priority", 0)) == 1,
        ))
    if monitors and not any(m.primary for m in monitors):
        monitors[0] = Monitor(**{**monitors[0].__dict__, "primary": True})
    return monitors


def _clean_env() -> dict[str, str]:
    # Steam's injected libraries can break Qt tools started from a launch option.
    return {k: v for k, v in os.environ.items() if k not in ("LD_PRELOAD", "LD_LIBRARY_PATH")}


def _run(cmd: list[str], timeout: float = 10) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_clean_env())
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or f"exit code {res.returncode}")
    return res.stdout


def detect_monitors() -> tuple[list[Monitor], str]:
    if shutil.which("kscreen-doctor") is None:
        return [], "kscreen-doctor not found"
    try:
        return parse_kscreen(_run(["kscreen-doctor", "-j"])), ""
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, KeyError, TypeError) as e:
        return [], f"kscreen-doctor: {e}"


# ---------------------------------------------------------------- panels

_QDBUS = ("qdbus6", "qdbus-qt6", "qdbus")

PANELS_SCRIPT = """
var out = [];
var ps = panels();
for (var i = 0; i < ps.length; i++) {
  var p = ps[i], g = null;
  try { var r = screenGeometry(p.screen); g = [r.x, r.y, r.width, r.height]; } catch (e) {}
  out.push({index: i, location: p.location, thickness: p.height, hiding: p.hiding,
            screen: p.screen, geometry: g});
}
print(JSON.stringify(out));
"""


def plasma_script(js: str) -> str:
    """Run a Plasma desktop script and return what it print()ed."""
    for tool in _QDBUS:
        if shutil.which(tool):
            return _run([tool, "org.kde.plasmashell", "/PlasmaShell",
                         "org.kde.PlasmaShell.evaluateScript", js])
    raise RuntimeError("no qdbus6/qdbus found")


def parse_panels(text: str) -> list[Panel]:
    panels = []
    for p in json.loads(text.strip() or "[]"):
        geo = p.get("geometry")
        if not (isinstance(geo, list) and len(geo) == 4 and all(isinstance(v, (int, float)) for v in geo)):
            geo = None
        panels.append(Panel(
            index=int(p["index"]), location=str(p.get("location", "")),
            thickness=int(p.get("thickness") or 0), hiding=str(p.get("hiding", "none")),
            screen=int(p.get("screen", -1) if p.get("screen") is not None else -1),
            geometry=tuple(round(v) for v in geo) if geo else None,
        ))
    return panels


def detect_panels() -> tuple[list[Panel], str]:
    try:
        return parse_panels(plasma_script(PANELS_SCRIPT)), ""
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, KeyError, TypeError) as e:
        return [], f"plasmashell: {e}"


def set_panel_hiding(modes: dict[int, str]) -> None:
    """Set hiding mode per panel index, e.g. {0: "autohide"}."""
    allowed = {"none", "autohide", "dodgewindows", "windowsgobelow"}
    lines = ["var ps = panels();"]
    for index, mode in sorted(modes.items()):
        if mode not in allowed:
            raise ValueError(f"unknown panel hiding mode {mode!r}")
        lines.append(f"if (ps.length > {int(index)}) ps[{int(index)}].hiding = {json.dumps(mode)};")
    plasma_script("\n".join(lines))


def detect() -> Live:
    monitors, merr = detect_monitors()
    panels, perr = detect_panels()
    return Live(monitors, panels, merr, perr)


def insets(panels: list[Panel], scale: float) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) in physical pixels taken up by always-visible panels."""
    edges = {"left": 0, "top": 0, "right": 0, "bottom": 0}
    for p in panels:
        if p.always_visible and p.location in edges:
            edges[p.location] = max(edges[p.location], round(p.thickness * scale))
    return edges["left"], edges["top"], edges["right"], edges["bottom"]
