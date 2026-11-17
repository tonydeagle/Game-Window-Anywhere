"""Build gamescope command lines and launcher-specific launch strings."""

from __future__ import annotations

import shlex

STEAM_PLACEHOLDER = "%command%"


def gamescope_args(
    out_w: int,
    out_h: int,
    render: tuple[int, int] | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    """Arguments for nested gamescope (everything except the binary and the game).

    -W/-H  : size of the gamescope window (the zone)
    -w/-h  : resolution the game renders at (defaults to the zone size)
    -b     : borderless window
    --force-grab-cursor : keep the mouse inside the game (needed by many titles)
    """
    rw, rh = render if render else (out_w, out_h)
    args = [
        "-W", str(out_w), "-H", str(out_h),
        "-w", str(rw), "-h", str(rh),
        "-b",
        "--force-grab-cursor",
    ]
    if extra:
        args += extra
    return args


def full_command(args: list[str], game_cmd: list[str], binary: str = "gamescope") -> list[str]:
    return [binary, *args, "--", *game_cmd]


def steam_launch_option(args: list[str]) -> str:
    """String to paste into Steam > game > Properties > Launch Options."""
    return f"{shlex.join(['gamescope', *args])} -- {STEAM_PLACEHOLDER}"


def heroic_wrapper(args: list[str]) -> tuple[str, str]:
    """(executable, arguments) for Heroic > game settings > Advanced > Wrapper command."""
    return "gamescope", f"{shlex.join(args)} --"
