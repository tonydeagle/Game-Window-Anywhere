"""Read/write a single managed rule in KWin's kwinrulesrc (Plasma 5.24+/6 format).

Format reminder::

    [General]
    count=2
    rules=<id-a>,<id-b>

    [<id-a>]
    Description=...
    wmclass=gamescope
    ...

We only ever touch ``[General]`` and our own group; every other line in the
file is preserved byte-for-byte. A backup is written before each change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .zones import Rect

# Deterministic id so re-running updates the same rule instead of adding more.
RULE_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/tonydeagle/game-window-anywhere#gamescope"))
DESCRIPTION_PREFIX = "Game Window Anywhere"

# KWin Rules::Type
FORCE = 2
# KWin Rules::StringMatch
EXACT_MATCH = 1
# NET::NormalMask
TYPE_NORMAL = 1


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "kwinrulesrc"


def build_rule(rect: Rect, wmclass: str = "gamescope", label: str = "") -> dict[str, str]:
    desc = f"{DESCRIPTION_PREFIX}: {wmclass}"
    if label:
        desc += f" ({label})"
    return {
        "Description": desc,
        "wmclass": wmclass,
        "wmclassmatch": str(EXACT_MATCH),
        "wmclasscomplete": "false",
        "types": str(TYPE_NORMAL),
        "position": f"{rect.x},{rect.y}",
        "positionrule": str(FORCE),
        "size": f"{rect.w},{rect.h}",
        "sizerule": str(FORCE),
        "noborder": "true",
        "noborderrule": str(FORCE),
        # Keep gamescope's own fullscreen toggle (Super+F) from escaping the zone.
        "fullscreen": "false",
        "fullscreenrule": str(FORCE),
    }


# --------------------------------------------------------------------------
# Minimal order-preserving KConfig reader/writer
# --------------------------------------------------------------------------

@dataclass
class _Group:
    header: str | None  # raw "[name]" line, None for lines before the first group
    name: str | None
    lines: list[str] = field(default_factory=list)


def _header_name(line: str) -> str | None:
    s = line.strip()
    if s.startswith("[") and s.endswith("]") and "=" not in s.split("]")[0]:
        return s[1:-1]
    return None


class KConfig:
    def __init__(self, text: str = ""):
        self.groups: list[_Group] = [_Group(None, None)]
        for raw in text.splitlines():
            name = _header_name(raw)
            if name is not None:
                self.groups.append(_Group(raw, name))
            else:
                self.groups[-1].lines.append(raw)

    @classmethod
    def load(cls, path: Path) -> "KConfig":
        return cls(path.read_text(encoding="utf-8") if path.exists() else "")

    def _find(self, name: str) -> _Group | None:
        for g in self.groups:
            if g.name == name:
                return g
        return None

    def has_group(self, name: str) -> bool:
        return self._find(name) is not None

    def get(self, group: str, key: str, default: str | None = None) -> str | None:
        g = self._find(group)
        if g is None:
            return default
        for line in g.lines:
            k, sep, v = line.partition("=")
            if sep and k.strip() == key:
                return v
        return default

    def items(self, group: str) -> dict[str, str]:
        g = self._find(group)
        out: dict[str, str] = {}
        if g:
            for line in g.lines:
                k, sep, v = line.partition("=")
                if sep and not k.lstrip().startswith("#"):
                    out[k.strip()] = v
        return out

    def set(self, group: str, key: str, value: str) -> None:
        g = self._find(group)
        if g is None:
            g = self._append_group(group)
        for i, line in enumerate(g.lines):
            k, sep, _ = line.partition("=")
            if sep and k.strip() == key:
                g.lines[i] = f"{key}={value}"
                return
        # insert before trailing blank lines so groups stay visually separated
        idx = len(g.lines)
        while idx > 0 and not g.lines[idx - 1].strip():
            idx -= 1
        g.lines.insert(idx, f"{key}={value}")

    def replace_group(self, group: str, values: dict[str, str]) -> None:
        g = self._find(group) or self._append_group(group)
        g.lines = [f"{k}={v}" for k, v in values.items()] + [""]

    def remove_group(self, group: str) -> bool:
        g = self._find(group)
        if g is None:
            return False
        self.groups.remove(g)
        return True

    def _append_group(self, name: str) -> _Group:
        last = self.groups[-1]
        if last.lines and last.lines[-1].strip():
            last.lines.append("")
        g = _Group(f"[{name}]", name, [""])
        self.groups.append(g)
        return g

    def dumps(self) -> str:
        out: list[str] = []
        for g in self.groups:
            if g.header is not None:
                out.append(g.header)
            out.extend(g.lines)
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out) + "\n" if out else ""


# --------------------------------------------------------------------------
# Rule list management
# --------------------------------------------------------------------------

def _rule_ids(cfg: KConfig) -> list[str]:
    raw = cfg.get("General", "rules", "") or ""
    return [r for r in (s.strip() for s in raw.split(",")) if r]


def _set_rule_ids(cfg: KConfig, ids: list[str]) -> None:
    cfg.set("General", "count", str(len(ids)))
    cfg.set("General", "rules", ",".join(ids))


def upsert_rule(cfg: KConfig, values: dict[str, str], rule_id: str = RULE_ID) -> None:
    ids = _rule_ids(cfg)
    if not cfg.has_group("General"):
        _set_rule_ids(cfg, ids)  # create [General] first so it stays at the top
    cfg.replace_group(rule_id, values)
    if rule_id not in ids:
        ids.append(rule_id)
    _set_rule_ids(cfg, ids)


def delete_rule(cfg: KConfig, rule_id: str = RULE_ID) -> bool:
    removed = cfg.remove_group(rule_id)
    ids = _rule_ids(cfg)
    if rule_id in ids:
        ids.remove(rule_id)
        removed = True
    if removed:
        _set_rule_ids(cfg, ids)
    return removed


def other_gamescope_rules(cfg: KConfig, wmclass: str = "gamescope", rule_id: str = RULE_ID) -> list[str]:
    """Descriptions of other rules that also match our window class (they may conflict)."""
    hits = []
    for rid in _rule_ids(cfg):
        if rid == rule_id:
            continue
        items = cfg.items(rid)
        if items.get("wmclass", "").strip().lower() == wmclass.lower():
            hits.append(items.get("Description", rid))
    return hits


def save(cfg: KConfig, path: Path) -> Path | None:
    """Write atomically; returns the backup path if a previous file existed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".gwa-backup")
        shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".gwa-tmp")
    tmp.write_text(cfg.dumps(), encoding="utf-8")
    os.replace(tmp, path)
    return backup


# --------------------------------------------------------------------------
# Tell KWin to reload
# --------------------------------------------------------------------------

_RECONFIGURE_CMDS = [
    ["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"],
    ["qdbus-qt6", "org.kde.KWin", "/KWin", "reconfigure"],
    ["qdbus", "org.kde.KWin", "/KWin", "reconfigure"],
    ["dbus-send", "--session", "--type=method_call", "--dest=org.kde.KWin",
     "/KWin", "org.kde.KWin.reconfigure"],
]


def reconfigure_kwin() -> tuple[bool, str]:
    """Try each known D-Bus client; return (ok, command-or-error)."""
    errors = []
    for cmd in _RECONFIGURE_CMDS:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"{cmd[0]}: {e}")
            continue
        if res.returncode == 0:
            return True, " ".join(cmd)
        errors.append(f"{cmd[0]}: {(res.stderr or res.stdout).strip()}")
    if not errors:
        return False, "no qdbus/qdbus6/dbus-send found"
    return False, "; ".join(errors)
