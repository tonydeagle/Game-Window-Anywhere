"""Auto-hide Plasma panels while a game runs, and always put them back.

State lives in ~/.cache/game-window-anywhere/taskbar.json:

    {"panels": {"0": "none"}, "pids": [12345]}

``panels`` holds the original hiding mode of each panel we changed; ``pids`` the gwa
processes currently relying on it. Panels are restored when the last pid is gone, and
stale pids (gwa was killed) are cleaned up by the next run or `gwa taskbar restore`.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from . import monitors as mon

SetHiding = Callable[[dict[int, str]], None]


def state_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "game-window-anywhere" / "taskbar.json"


@contextmanager
def _locked_state():
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            state = {}
        state.setdefault("panels", {})
        state.setdefault("pids", [])
        yield state
        if state["panels"] or state["pids"]:
            path.write_text(json.dumps(state))
        elif path.exists():
            path.unlink()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _setter(set_hiding: SetHiding | None) -> SetHiding:
    return set_hiding or mon.set_panel_hiding  # looked up at call time (patchable in tests)


def _restore_if_unused(state: dict, set_hiding: SetHiding | None) -> dict[int, str]:
    state["pids"] = [p for p in state["pids"] if _alive(p)]
    if state["pids"] or not state["panels"]:
        return {}
    original = {int(k): v for k, v in state["panels"].items()}
    _setter(set_hiding)(original)
    state["panels"] = {}
    return original


def begin(panels: list[mon.Panel], pid: int, set_hiding: SetHiding | None = None) -> list[int]:
    """Auto-hide the always-visible ``panels`` for game process ``pid``. Returns panels changed."""
    with _locked_state() as state:
        _restore_if_unused(state, set_hiding)  # tidy up after a killed gwa first
        changes = {p.index: "autohide" for p in panels
                   if p.always_visible and str(p.index) not in state["panels"]}
        if changes:
            _setter(set_hiding)(changes)
            for p in panels:
                if p.index in changes:
                    state["panels"][str(p.index)] = p.hiding
        state["pids"].append(pid)
        return sorted(changes)


def end(pid: int, set_hiding: SetHiding | None = None) -> dict[int, str]:
    """Game ``pid`` finished. Restores panels if no other game still needs them hidden."""
    with _locked_state() as state:
        state["pids"] = [p for p in state["pids"] if p != pid]
        return _restore_if_unused(state, set_hiding)


def restore(force: bool = False, set_hiding: SetHiding | None = None) -> dict[int, str]:
    """Put panels back. Without ``force`` only when no running game still uses auto-hide."""
    with _locked_state() as state:
        if force:
            state["pids"] = []
        return _restore_if_unused(state, set_hiding)


def status() -> dict:
    with _locked_state() as state:
        return {"panels": dict(state["panels"]), "pids": [p for p in state["pids"] if _alive(p)]}
