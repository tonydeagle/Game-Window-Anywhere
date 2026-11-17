"""gwa — run games "fullscreen" inside a zone of your monitor via gamescope + a KWin rule."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__, core, gamescope, kwinrules, presets
from .presets import Settings
from .zones import PRESETS, Rect, compute_zone, parse_point, parse_rect, parse_size


def _arg(fn):
    """Wrap a parser so argparse reports ValueError messages nicely."""
    def inner(text):
        try:
            return fn(text)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e)) from None
    inner.__name__ = fn.__name__
    return inner


def _die(msg: str) -> None:
    sys.exit(f"gwa: error: {msg}")


# ---------------------------------------------------------------- parsers

def _presets_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--presets-file", type=Path, default=None,
                   help="path to presets.toml (default: $XDG_CONFIG_HOME/game-window-anywhere/presets.toml)")
    return p


def _zone_options() -> argparse.ArgumentParser:
    """Zone/gamescope options. Every default is None so we can tell 'not given' apart."""
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("zone")
    g.add_argument("--screen", type=_arg(parse_size), metavar="WxH",
                   help="monitor resolution in pixels (default: 3440x1440)")
    g.add_argument("--width", type=int, metavar="PX",
                   help="zone width for left/right/center (default: half the screen)")
    g.add_argument("--height", type=int, metavar="PX",
                   help="zone height for left/right/center (default: full height)")
    g.add_argument("--rect", type=_arg(parse_rect), metavar="X,Y,W,H",
                   help="zone for the custom zone (also accepts WxH+X+Y)")
    g.add_argument("--origin", type=_arg(parse_point), metavar="X,Y",
                   help="top-left of the monitor in KWin's global layout, for multi-monitor setups")
    g.add_argument("--scale", type=float,
                   help="display scale factor (e.g. 1.25); KWin rule uses logical pixels")

    gs = p.add_argument_group("gamescope")
    gs.add_argument("--render", type=_arg(parse_size), metavar="WxH",
                    help="resolution the game renders at (-w/-h); default: the zone size")
    gs.add_argument("--gamescope-args", metavar="ARGS",
                    help='extra gamescope flags, e.g. "-r 144 -F fsr"')
    gs.add_argument("--wmclass", help="window class the KWin rule matches (default: gamescope)")
    return p


def _kwin_options() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    k = p.add_argument_group("kwin")
    k.add_argument("--rules-file", type=Path, default=None,
                   help="path to kwinrulesrc (default: $XDG_CONFIG_HOME/kwinrulesrc)")
    k.add_argument("--no-reconfigure", action="store_true",
                   help="write the rule but don't ask KWin to reload")
    return p


TARGET_HELP = f"a built-in zone ({', '.join(PRESETS)}) or the name of a saved preset"


# ---------------------------------------------------------------- settings

def _presets_path(args) -> Path:
    return args.presets_file or presets.default_path()


def _load_presets(args) -> dict[str, Settings]:
    try:
        return presets.load(_presets_path(args))
    except ValueError as e:
        _die(str(e))


def _cli_overrides(args) -> dict:
    return {name: getattr(args, name, None) for name in presets.FIELD_NAMES if name not in ("zone", "command")}


def _settings(args) -> tuple[str, Settings, bool]:
    """Resolve args.target (+ any CLI overrides) into (label, Settings, is_saved_preset)."""
    target = args.target
    if target in PRESETS:
        base, saved = Settings(zone=target), False
    else:
        stored = _load_presets(args)
        if target not in stored:
            known = ", ".join(sorted(stored)) or "none yet"
            _die(f"'{target}' is not a zone ({', '.join(PRESETS)}) or a saved preset "
                 f"(saved: {known})")
        base, saved = stored[target], True
    return target, base.merged(**_cli_overrides(args)), saved


def _resolve(s: Settings) -> tuple[Rect, Rect, list[str]]:
    """Return (zone in physical px, kwin geometry in logical px, gamescope args)."""
    try:
        p = core.plan(s)
    except ValueError as e:
        _die(str(e))
    for w in p.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return p.zone, p.kwin_rect, p.gamescope_args


def _describe(s: Settings) -> str:
    """One-line summary used by `list` and `save`."""
    try:
        zone = compute_zone(s.zone, s.screen, s.width, s.height, s.rect)
        geo = f"{zone.w}x{zone.h} at {zone.x},{zone.y}"
    except ValueError as e:
        geo = f"INVALID: {e}"
    extras = []
    if s.render:
        extras.append(f"render {s.render[0]}x{s.render[1]}")
    if s.screen != presets.DEFAULTS.screen:
        extras.append(f"screen {s.screen[0]}x{s.screen[1]}")
    if s.origin != presets.DEFAULTS.origin:
        extras.append(f"origin {s.origin[0]},{s.origin[1]}")
    if s.scale != presets.DEFAULTS.scale:
        extras.append(f"scale {s.scale:g}")
    if s.gamescope_args:
        extras.append(f"gamescope {s.gamescope_args!r}")
    return f"{s.zone:<6} {geo}" + (f"  ({', '.join(extras)})" if extras else "")


# ---------------------------------------------------------------- kwin + output

def _rules_path(args) -> Path:
    return args.rules_file or kwinrules.default_path()


# KWin applies a reconfigure on a short timer, while gamescope maps its window almost
# instantly; without a pause the window can open under the previous rule.
RELOAD_SETTLE_SECONDS = 1.0


def _write_rule(args, s: Settings, label: str, kwin_rect: Rect, dry_run: bool = False) -> str:
    """Write the rule and reload KWin. Returns a one-line outcome for the run log."""
    values = kwinrules.build_rule(kwin_rect, s.wmclass, f"{label} {kwin_rect}")
    path = _rules_path(args)

    if dry_run:
        print(f"# would write to {path}:")
        print(f"[{kwinrules.RULE_ID}]")
        for k, v in values.items():
            print(f"{k}={v}")
        return "dry run"

    backup, conflicts = core.write_rule(s, label, kwin_rect, path)
    for other in conflicts:
        print(f"warning: another KWin rule also matches '{s.wmclass}' and may conflict: {other}",
              file=sys.stderr)
    print(f"KWin rule written: {path}" + (f" (backup: {backup.name})" if backup else ""))

    if args.no_reconfigure:
        return "rule written, reload skipped"
    ok, info = kwinrules.reconfigure_kwin()
    if ok:
        print("KWin reconfigured.")
        return f"rule written, KWin reconfigured via {info.split()[0]}"
    print(f"warning: couldn't reconfigure KWin ({info}).\n"
          "         Run: qdbus6 org.kde.KWin /KWin reconfigure", file=sys.stderr)
    return f"rule written, KWin reload FAILED: {info}"


# Launchers pass credentials on the command line (Heroic/Legendary: -AUTH_PASSWORD=<exchange code>).
_SECRET_ARG = re.compile(r"^(-{0,2}[\w.-]*(?:password|passwd|token|secret|apikey|api_key)[\w.-]*=).+$",
                         re.IGNORECASE)


def redact(cmd: list[str]) -> list[str]:
    """Hide the values of key=value arguments that look like credentials."""
    return [_SECRET_ARG.sub(r"\1<redacted>", a) for a in cmd]


def _log_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "game-window-anywhere" / "run.log"


def _log_run(lines: list[str]) -> None:
    """Append to run.log: Steam/Heroic hide gwa's output, so keep a record. Never fatal."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 256 * 1024:
            path.replace(path.with_suffix(".log.old"))
        stamp = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(f"{stamp} {line}\n")
    except OSError:
        pass


def _print_launch_options(zone: Rect, gs_args: list[str], preset_name: str | None = None) -> None:
    exe, wrapper_args = gamescope.heroic_wrapper(gs_args)
    print()
    print(f"Zone: {zone.w}x{zone.h} at {zone.x},{zone.y}")
    print()
    print("Steam → Properties → Launch Options:")
    print(f"  {gamescope.steam_launch_option(gs_args)}")
    print()
    print("Heroic → Game settings → Advanced → Wrapper command:")
    print(f"  Executable: {exe}")
    print(f"  Arguments:  {wrapper_args}")
    print()
    print("Any other launcher / terminal:")
    print(f"  {shlex.join(['gamescope', *gs_args])} -- <game command>")
    if preset_name:
        steam, exe, wrapper = core.preset_launch_options(preset_name)
        print()
        print(f"Or let gwa switch to the '{preset_name}' zone every time the game starts:")
        print(f"  Steam:  {steam}")
        print(f"  Heroic: Executable: {exe}   Arguments: {wrapper}")


# ---------------------------------------------------------------- commands

def cmd_apply(args) -> int:
    label, s, saved = _settings(args)
    zone, kwin_rect, gs_args = _resolve(s)
    _write_rule(args, s, label, kwin_rect, dry_run=args.dry_run)
    _print_launch_options(zone, gs_args, label if saved else None)
    return 0


def cmd_run(args) -> int:
    label, s, _ = _settings(args)
    game = list(args.command) or list(s.command)
    if not game:
        _die(f"no game command: use `gwa run {label} -- <command>`"
             + ("" if args.target in PRESETS else f" or save one with `gwa save {label} ... -- <command>`"))
    binary = shutil.which("gamescope")
    if binary is None:
        _die("gamescope not found in PATH")
    zone, kwin_rect, gs_args = _resolve(s)
    outcome = _write_rule(args, s, label, kwin_rect)
    cmd = gamescope.full_command(gs_args, game, binary)
    shown = shlex.join(redact(cmd))
    _log_run([f"run {label}: zone {kwin_rect}", f"  {outcome}", f"  exec: {shown}"])
    if "reconfigured" in outcome:
        time.sleep(RELOAD_SETTLE_SECONDS)
    print(f"exec: {shown}", flush=True)
    os.execv(binary, cmd)
    return 0  # unreachable


def cmd_save(args) -> int:
    try:
        presets.validate_name(args.name)
    except ValueError as e:
        _die(str(e))
    _, s, _ = _settings(args)
    if args.command:
        s = s.merged(command=tuple(args.command))
    _resolve(s)  # validate before saving anything

    path = _presets_path(args)
    stored = _load_presets(args)
    existed = args.name in stored
    stored[args.name] = s
    presets.save(stored, path)
    print(f"{'Updated' if existed else 'Saved'} preset '{args.name}' in {path}")
    print(f"  {_describe(s)}")
    if s.command:
        print(f"  command: {shlex.join(s.command)}")
    print()
    print(f"Apply it with:  gwa apply {args.name}")
    print(f"Launch with:    gwa run {args.name}" + ("" if s.command else " -- <game command>"))
    return 0


def cmd_list(args) -> int:
    stored = _load_presets(args)
    if not stored:
        print(f"No saved presets ({_presets_path(args)}).")
        print("Create one with e.g.:  gwa save rocketleague right --width 2560")
        return 0
    width = max(len(n) for n in stored)
    for name in sorted(stored):
        s = stored[name]
        print(f"{name:<{width}}  {_describe(s)}")
        if s.command:
            print(f"{'':<{width}}  command: {shlex.join(s.command)}")
    return 0


def cmd_delete(args) -> int:
    stored = _load_presets(args)
    if args.name not in stored:
        _die(f"no saved preset named '{args.name}'")
    del stored[args.name]
    presets.save(stored, _presets_path(args))
    print(f"Deleted preset '{args.name}'.")
    return 0


def cmd_gui(args) -> int:
    try:
        from . import gui
    except ImportError as e:
        _die(f"the GUI needs PySide6 ({e}).\n"
             "  Arch:          sudo pacman -S pyside6\n"
             "  Fedora:        sudo dnf install python3-pyside6\n"
             "  Debian/Ubuntu: sudo apt install python3-pyside6.qtwidgets\n"
             "  openSUSE:      sudo zypper install python3-pyside6\n"
             "  or with pip:   pip install --user PySide6-Essentials")
    return gui.main(args.presets_file)


def cmd_status(args) -> int:
    path = _rules_path(args)
    cfg = kwinrules.KConfig.load(path)
    if not cfg.has_group(kwinrules.RULE_ID):
        print(f"No Game Window Anywhere rule in {path}.")
        return 1
    print(f"[{kwinrules.RULE_ID}] in {path}")
    for k, v in cfg.items(kwinrules.RULE_ID).items():
        print(f"  {k}={v}")
    return 0


def cmd_remove(args) -> int:
    path = _rules_path(args)
    cfg = kwinrules.KConfig.load(path)
    if not kwinrules.delete_rule(cfg):
        print(f"No Game Window Anywhere rule in {path}; nothing to do.")
        return 0
    kwinrules.save(cfg, path)
    print(f"Rule removed from {path}.")
    if not args.no_reconfigure:
        ok, info = kwinrules.reconfigure_kwin()
        print("KWin reconfigured." if ok else f"warning: couldn't reconfigure KWin ({info}).")
    return 0


# commands that accept "-- <game command>"
TAKES_COMMAND = {"run", "save"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gwa",
        description="Run games 'fullscreen' inside part of your monitor (gamescope + KWin rule).",
        epilog="examples:\n"
               "  gwa apply left                      # left half of 3440x1440\n"
               "  gwa apply right --width 1920        # 1920x1440 on the right\n"
               "  gwa apply custom --rect 760,0,1920,1080\n"
               "  gwa run left -- ./SlayTheSpire      # write rule and launch directly\n"
               "\n"
               "  gwa save rocketleague right --width 2560\n"
               "  gwa save spire left -- ~/Games/SlayTheSpire/SlayTheSpire\n"
               "  gwa apply rocketleague              # presets work wherever zones do\n"
               "  gwa run spire\n"
               "  gwa list | gwa delete spire | gwa remove",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")
    zone, kwin, pre = _zone_options(), _kwin_options(), _presets_parser()

    a = sub.add_parser("apply", parents=[zone, kwin, pre],
                       help="write the KWin rule for a zone or preset and print launch options")
    a.add_argument("target", metavar="ZONE|PRESET", help=TARGET_HELP)
    a.add_argument("--dry-run", action="store_true", help="print the rule instead of writing it")
    a.set_defaults(func=cmd_apply)

    r = sub.add_parser("run", parents=[zone, kwin, pre],
                       usage="gwa run [options] ZONE|PRESET [-- GAME COMMAND...]",
                       help="write the KWin rule, then launch a game in gamescope")
    r.add_argument("target", metavar="ZONE|PRESET", help=TARGET_HELP)
    r.set_defaults(func=cmd_run)

    sv = sub.add_parser("save", parents=[zone, pre],
                        usage="gwa save [options] NAME ZONE|PRESET [-- GAME COMMAND...]",
                        help="save a named per-game preset")
    sv.add_argument("name", help="preset name, e.g. rocketleague")
    sv.add_argument("target", metavar="ZONE|PRESET",
                    help="zone to base it on (or an existing preset to copy)")
    sv.set_defaults(func=cmd_save)

    ls = sub.add_parser("list", parents=[pre], help="show saved presets")
    ls.set_defaults(func=cmd_list)

    d = sub.add_parser("delete", parents=[pre], help="delete a saved preset")
    d.add_argument("name")
    d.set_defaults(func=cmd_delete)

    g = sub.add_parser("gui", parents=[pre], help="open the preset editor window")
    g.set_defaults(func=cmd_gui)

    rules = argparse.ArgumentParser(add_help=False)
    rules.add_argument("--rules-file", type=Path, default=None, help="path to kwinrulesrc")
    s = sub.add_parser("status", parents=[rules], help="show the current KWin rule")
    s.set_defaults(func=cmd_status)
    rm = sub.add_parser("remove", parents=[rules], help="delete the KWin rule")
    rm.add_argument("--no-reconfigure", action="store_true")
    rm.set_defaults(func=cmd_remove)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Split off "-- <game command>" ourselves: argparse.REMAINDER would also swallow any
    # options written after the positional arguments.
    command: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if command and args.cmd not in TAKES_COMMAND:
        parser.error(f"'{args.cmd}' doesn't take a game command after --")
    args.command = command
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
