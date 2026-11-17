"""gwa — run games "fullscreen" inside a zone of your monitor via gamescope + a KWin rule."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path

from . import __version__, gamescope, kwinrules
from .zones import DEFAULT_SCREEN, PRESETS, Rect, compute_zone, fits, parse_point, parse_rect, parse_size


def _arg(fn):
    """Wrap a parser so argparse reports ValueError messages nicely."""
    def inner(text):
        try:
            return fn(text)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e)) from None
    inner.__name__ = fn.__name__
    return inner


def _zone_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group("zone")
    g.add_argument("preset", choices=PRESETS, help="where to put the game")
    g.add_argument("--screen", type=_arg(parse_size), default=DEFAULT_SCREEN, metavar="WxH",
                   help="monitor resolution in pixels (default: 3440x1440)")
    g.add_argument("--width", type=int, metavar="PX",
                   help="zone width for left/right/center (default: half the screen)")
    g.add_argument("--height", type=int, metavar="PX",
                   help="zone height for left/right/center (default: full height)")
    g.add_argument("--rect", type=_arg(parse_rect), metavar="X,Y,W,H",
                   help="zone for the custom preset (also accepts WxH+X+Y)")
    g.add_argument("--origin", type=_arg(parse_point), default=(0, 0), metavar="X,Y",
                   help="top-left of the monitor in KWin's global layout, for multi-monitor setups")
    g.add_argument("--scale", type=float, default=1.0,
                   help="display scale factor (e.g. 1.25); KWin rule uses logical pixels")

    gs = p.add_argument_group("gamescope")
    gs.add_argument("--render", type=_arg(parse_size), metavar="WxH",
                    help="resolution the game renders at (-w/-h); default: the zone size")
    gs.add_argument("--gamescope-args", default="", metavar="ARGS",
                    help='extra gamescope flags, e.g. "-r 144 -F fsr"')

    k = p.add_argument_group("kwin")
    k.add_argument("--wmclass", default="gamescope", help="window class to match (default: %(default)s)")
    k.add_argument("--rules-file", type=Path, default=None,
                   help="path to kwinrulesrc (default: $XDG_CONFIG_HOME/kwinrulesrc)")
    k.add_argument("--no-reconfigure", action="store_true",
                   help="write the rule but don't ask KWin to reload")
    return p


def _resolve(args) -> tuple[Rect, Rect, list[str]]:
    """Return (zone in physical px, kwin geometry in logical px, gamescope args)."""
    try:
        zone = compute_zone(args.preset, args.screen, args.width, args.height, args.rect)
    except ValueError as e:
        sys.exit(f"gwa: error: {e}")
    if args.scale <= 0:
        sys.exit("gwa: error: --scale must be positive")
    if args.preset == "custom" and not fits(zone, args.screen):
        print(f"warning: zone {zone} extends past the {args.screen[0]}x{args.screen[1]} screen",
              file=sys.stderr)
    kwin_rect = zone.scaled(args.scale).offset(*args.origin)
    gs_args = gamescope.gamescope_args(zone.w, zone.h, args.render, shlex.split(args.gamescope_args))
    return zone, kwin_rect, gs_args


def _rules_path(args) -> Path:
    return args.rules_file or kwinrules.default_path()


def _write_rule(args, kwin_rect: Rect, dry_run: bool = False) -> None:
    label = f"{args.preset} {kwin_rect}"
    values = kwinrules.build_rule(kwin_rect, args.wmclass, label)
    path = _rules_path(args)

    if dry_run:
        print(f"# would write to {path}:")
        print(f"[{kwinrules.RULE_ID}]")
        for k, v in values.items():
            print(f"{k}={v}")
        return

    cfg = kwinrules.KConfig.load(path)
    for other in kwinrules.other_gamescope_rules(cfg, args.wmclass):
        print(f"warning: another KWin rule also matches '{args.wmclass}' and may conflict: {other}",
              file=sys.stderr)
    kwinrules.upsert_rule(cfg, values)
    backup = kwinrules.save(cfg, path)
    print(f"KWin rule written: {path}" + (f" (backup: {backup.name})" if backup else ""))

    if args.no_reconfigure:
        return
    ok, info = kwinrules.reconfigure_kwin()
    if ok:
        print("KWin reconfigured.")
    else:
        print(f"warning: couldn't reconfigure KWin ({info}).\n"
              "         Run: qdbus6 org.kde.KWin /KWin reconfigure", file=sys.stderr)


def _print_launch_options(zone: Rect, gs_args: list[str]) -> None:
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


# ---------------------------------------------------------------- commands

def cmd_apply(args) -> int:
    zone, kwin_rect, gs_args = _resolve(args)
    _write_rule(args, kwin_rect, dry_run=args.dry_run)
    _print_launch_options(zone, gs_args)
    return 0


def cmd_run(args) -> int:
    game = args.command
    if game and game[0] == "--":
        game = game[1:]
    if not game:
        sys.exit("gwa: error: give the game command after --, e.g. gwa run left -- ./SlayTheSpire")
    binary = shutil.which("gamescope")
    if binary is None:
        sys.exit("gwa: error: gamescope not found in PATH")
    zone, kwin_rect, gs_args = _resolve(args)
    _write_rule(args, kwin_rect)
    cmd = gamescope.full_command(gs_args, game, binary)
    print(f"exec: {shlex.join(cmd)}", flush=True)
    os.execv(binary, cmd)
    return 0  # unreachable


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gwa",
        description="Run games 'fullscreen' inside part of your monitor (gamescope + KWin rule).",
        epilog="examples:\n"
               "  gwa apply left                      # left half of 3440x1440\n"
               "  gwa apply right --width 1920        # 1920x1440 on the right\n"
               "  gwa apply custom --rect 760,0,1920,1080\n"
               "  gwa run left -- ./SlayTheSpire      # write rule and launch directly\n"
               "  gwa remove",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    zone = _zone_parser()

    a = sub.add_parser("apply", parents=[zone], help="write the KWin rule and print launch options")
    a.add_argument("--dry-run", action="store_true", help="print the rule instead of writing it")
    a.set_defaults(func=cmd_apply)

    r = sub.add_parser("run", parents=[zone], help="write the KWin rule, then launch a game in gamescope")
    r.add_argument("command", nargs=argparse.REMAINDER, help="-- <game command...>")
    r.set_defaults(func=cmd_run)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--rules-file", type=Path, default=None, help="path to kwinrulesrc")
    s = sub.add_parser("status", parents=[common], help="show the current rule")
    s.set_defaults(func=cmd_status)
    rm = sub.add_parser("remove", parents=[common], help="delete the rule")
    rm.add_argument("--no-reconfigure", action="store_true")
    rm.set_defaults(func=cmd_remove)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
