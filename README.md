# Game Window Anywhere

Run games "fullscreen" in **part** of your monitor on KDE Plasma (Wayland), for example
the left half of a 3440x1440 ultrawide while Discord or a browser fills the other half.
It works like FancyZones, but for games.

## How it works

1. The game runs inside **nested [gamescope](https://github.com/ValveSoftware/gamescope)**
   with an output size equal to the zone. The game thinks it is fullscreen at that resolution.
2. A **KWin window rule** for the window class `gamescope` forces the window's position and
   size and removes the titlebar and frame, so it lands exactly in the zone.

`gwa` does both: it writes the rule to `~/.config/kwinrulesrc`, asks KWin to reload, and prints
the launch option to paste into Steam or Heroic.

## Requirements

- KDE Plasma 5.24+ or 6 (tested target: Plasma 6, Wayland)
- `gamescope`
- Python 3.11+ (standard library only)
- `qdbus6`, `qdbus` or `dbus-send` to reload KWin (one of them is almost always present)

## Install

```sh
git clone https://github.com/tonydeagle/game-window-anywhere
cd game-window-anywhere
./gwa --help              # run from the checkout
# or: pipx install .      # puts `gwa` on your PATH
```

## Usage

```sh
gwa apply left                         # 1720x1440 at 0,0
gwa apply right                        # 1720x1440 at 1720,0
gwa apply right --width 2560           # 2560x1440 at 880,0
gwa apply center --width 2560          # 2560x1440 at 440,0
gwa apply custom --rect 760,180,1920,1080
gwa apply left --dry-run               # show the rule, write nothing
gwa status                             # show the current rule
gwa remove                             # delete it
```

`apply` prints something like:

```
Steam → Properties → Launch Options:
  gamescope -W 1720 -H 1440 -w 1720 -h 1440 -b --force-grab-cursor -- %command%

Heroic → Game settings → Advanced → Wrapper command:
  Executable: gamescope
  Arguments:  -W 1720 -H 1440 -w 1720 -h 1440 -b --force-grab-cursor --
```

To skip the launcher, `gwa run` writes the rule and then starts gamescope directly:

```sh
gwa run left -- ~/Games/SlayTheSpire/SlayTheSpire
```

### GUI

```sh
gwa gui
```

A preset editor window with a blue theme. It has:

- a list of your games
- a live preview of your monitor with the zone drawn on it
- a scrollable list of game sizes that fit your screen (half, two-thirds and one-third width,
  then common resolutions), plus **Custom size…** for anything non-standard
- Left / Center / Right / Custom positions
- an optional lower render resolution for upscaling
- the Steam and Heroic launch options, each with a Copy button
- a short description under every setting

Changes are kept until you click **Save** (Ctrl+S). Unsaved games show a • in the list, and
closing the window asks whether to save, discard or cancel. **Apply zone now** writes the KWin
rule straight away without launching anything.

The GUI needs PySide6 (the CLI doesn't):

| Distro | Install |
|---|---|
| Arch | `sudo pacman -S pyside6` |
| Fedora | `sudo dnf install python3-pyside6` |
| Debian / Ubuntu | `sudo apt install python3-pyside6.qtwidgets` |
| openSUSE | `sudo zypper install python3-pyside6` |
| pip | `pip install --user PySide6-Essentials` |

### Per-game presets

Save a zone once per game, then refer to it by name anywhere you'd write `left` or `right`:

```sh
gwa save rocketleague right --width 2560
gwa save spire left -- ~/Games/SlayTheSpire/SlayTheSpire   # optionally store the game command
gwa list
gwa apply rocketleague          # write the rule + print launch options
gwa run spire                   # write the rule + launch the saved command
gwa apply rocketleague --width 1920   # flags override the preset for this one time
gwa save rl-small rocketleague --width 1920   # copy a preset with changes
gwa delete spire
```

Presets live in `~/.config/game-window-anywhere/presets.toml`, a plain file you can also edit
by hand. Only settings that differ from the defaults are stored.

**Switch zones automatically per game.** Because a single KWin rule covers every gamescope
window, the most recently applied zone is the one that's used. To have each game pick its own
zone when it starts, let `gwa` run gamescope for it. `gwa apply <preset>` prints these lines
with the full path filled in:

```
Steam launch option:   /path/to/gwa run rocketleague -- %command%
Heroic wrapper:        Executable /path/to/gwa, Arguments: run rocketleague --
```

### Troubleshooting a launch

When Steam or Heroic starts `gwa run`, its messages aren't shown anywhere, so each run is also
logged to `~/.cache/game-window-anywhere/run.log`: which preset, the zone, whether KWin reloaded,
and the exact gamescope command. If a game opens in the wrong place, that file is the first
thing to check.

`gwa run` waits about a second after KWin confirms the reload before starting gamescope.
KWin applies rule changes on a short delay, and without the wait a game could open under the
previous game's zone.

### Options

| Option | Meaning |
|---|---|
| `--screen WxH` | Monitor resolution (default `3440x1440`) |
| `--width / --height` | Zone size for `left` / `right` / `center` (default: half width, full height) |
| `--rect X,Y,W,H` | Zone for `custom` (also accepts `WxH+X+Y`) |
| `--origin X,Y` | The monitor's top-left in KWin's global layout (multi-monitor) |
| `--scale F` | Display scale (e.g. `1.25`). The KWin rule uses logical pixels and gamescope uses real pixels |
| `--render WxH` | Resolution the game renders at (gamescope `-w/-h`), for upscaling |
| `--gamescope-args "..."` | Extra gamescope flags, e.g. `"-r 144"` or `"-F fsr"` |
| `--wmclass` | Window class to match (default `gamescope`) |
| `--rules-file` | Alternative path to `kwinrulesrc` |
| `--no-reconfigure` | Write the rule but don't reload KWin |

## Game notes

- **Slay the Spire (native):** Steam launch option as printed. Choose the zone resolution in
  the game's settings and set it to fullscreen or borderless.
- **Rocket League (Steam, Proton):** Steam launch option as printed. In game, set
  *Display Mode: Fullscreen* and the resolution to match the zone.
- **Rocket League (Heroic / Epic):** use the Wrapper command shown above. Alternatively, use
  Heroic's built-in Gamescope section with Game/Upscale size = zone size and *Borderless* and
  *Force grab cursor* checked. The KWin rule still handles placement.

## Tested on

| Setup | Result |
|---|---|
| KDE Plasma 6, Wayland, 3440x1440 ultrawide | `left`/`right` and presets: window placed exactly, no frame |
| Slay the Spire 2 (Steam, Steam Linux Runtime) | Works at 1720x1440 left; `gwa run spire -- %command%` launch option |
| Rocket League (Heroic / Epic, via umu-run) | Works at 1720x1440 and 2560x1440 right, no noticeable input lag; Heroic wrapper `gwa run rocketleague --` |
| Automatic switching | Launching the two games alternately (twice each) puts each in its own zone every time |
| `vkcube` in nested gamescope | Lands in the zone; KWin reports class `gamescope` |

`center`, `custom`, `--origin` and `--scale` have unit tests but haven't been tried on real
hardware yet. Reports are welcome.

## Safety

- `gwa` changes only its own rule, which has a fixed UUID, plus the `count` / `rules` keys in
  `[General]`. All other rules are left untouched.
- Before each write it saves `kwinrulesrc.gwa-backup` next to the original.
- It warns you if another rule already matches `gamescope`.

## Limitations and roadmap

- There is one zone at a time, because every gamescope window has the class `gamescope`.
  Running two games in two zones at once would need per-instance window matching.
- Planned: monitor detection via `kscreen-doctor`, and an app-menu entry for the GUI.

## Development

```sh
python3 -m unittest discover -s tests -v
```

## License

MIT
