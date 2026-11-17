"""Install / remove the app-menu entry and icon for the GUI (per user, no root needed)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DESKTOP_ID = "game-window-anywhere"
ICON_SOURCE = Path(__file__).resolve().parent / "assets" / f"{DESKTOP_ID}.svg"

# Characters that force quoting in a desktop-entry Exec argument (Desktop Entry spec, "Exec key").
_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local/share"))


def desktop_path() -> Path:
    return data_home() / "applications" / f"{DESKTOP_ID}.desktop"


def icon_path() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{DESKTOP_ID}.svg"


def exec_arg(arg: str) -> str:
    """Quote one argument for the Exec key."""
    arg = arg.replace("%", "%%")  # % starts a field code
    if any(c in _RESERVED for c in arg):
        for c in '\\"`$':
            arg = arg.replace(c, "\\" + c)
        arg = f'"{arg}"'
    # Exec is also a "string" value, where a backslash must itself be escaped.
    return arg.replace("\\", "\\\\")


def entry_text(gwa: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.5",
        "Name=Game Window Anywhere",
        "GenericName=Game zone manager",
        "Comment=Play games fullscreen in part of your monitor",
        f"Exec={exec_arg(gwa)} gui",
        f"Icon={DESKTOP_ID}",
        "Terminal=false",
        "Categories=Game;",
        "Keywords=gamescope;ultrawide;zone;fullscreen;window;kwin;",
        f"StartupWMClass={DESKTOP_ID}",
        "",
    ])


def refresh_menu() -> str:
    """Ask Plasma to pick up the change now (it also notices on its own, just later)."""
    env = {k: v for k, v in os.environ.items() if k not in ("LD_PRELOAD", "LD_LIBRARY_PATH")}
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(tool):
            try:
                subprocess.run([tool], capture_output=True, timeout=60, env=env)
                return tool
            except (OSError, subprocess.TimeoutExpired):
                pass
    return ""


def install(gwa: str) -> list[Path]:
    icon = icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON_SOURCE, icon)
    entry = desktop_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    tmp = entry.with_name(entry.name + ".tmp")
    tmp.write_text(entry_text(gwa), encoding="utf-8")
    os.replace(tmp, entry)
    return [entry, icon]


def uninstall() -> list[Path]:
    removed = []
    for p in (desktop_path(), icon_path()):
        if p.exists():
            p.unlink()
            removed.append(p)
    return removed
