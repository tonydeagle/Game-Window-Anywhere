import contextlib
import io
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gwa import cli, presets  # noqa: E402
from gwa.presets import Settings  # noqa: E402
from gwa.zones import Rect  # noqa: E402


class Serialisation(unittest.TestCase):
    def test_only_non_defaults_stored(self):
        self.assertEqual(presets.to_table(Settings(zone="right")), {"zone": "right"})
        self.assertEqual(presets.to_table(Settings(zone="right", width=2560, render=(1280, 720))),
                         {"zone": "right", "width": 2560, "render": "1280x720"})

    def test_roundtrip_all_fields(self):
        s = Settings(zone="custom", screen=(2560, 1440), rect=Rect(10, 20, 800, 600),
                     origin=(-1920, 0), scale=1.25, render=(640, 480),
                     gamescope_args='-r 144 --name "a b"', wmclass="gs",
                     command=("/opt/My Game/run", "--opt", 'quote"d', "ünï"))
        text = presets.dumps({"x": s})
        loaded = {n: presets.from_table(n, t) for n, t in tomllib.loads(text).items()}
        self.assertEqual(loaded, {"x": s})

    def test_bad_values_name_the_preset_and_key(self):
        cases = [
            ({"zone": "top"}, "zone"),
            ({"zone": "left", "width": "wide"}, "width"),
            ({"zone": "left", "width": True}, "width"),
            ({"zone": "left", "screen": "big"}, "screen"),
            ({"zone": "left", "command": "./game"}, "command"),
            ({"zone": "left", "colour": "red"}, "colour"),
        ]
        for table, key in cases:
            with self.subTest(table=table):
                with self.assertRaisesRegex(ValueError, f"preset 'rl': {key}"):
                    presets.from_table("rl", table)

    def test_names(self):
        presets.validate_name("rocket-league_2")
        for bad in ("left", "custom", "", "-x", "has space", "a/b", "x" * 65):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                presets.validate_name(bad)

    def test_merged_ignores_none(self):
        s = Settings(zone="right", width=2560).merged(width=None, height=1080)
        self.assertEqual((s.width, s.height), (2560, 1080))


class CliPresets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.presets_file = d / "presets.toml"
        self.rules_file = d / "kwinrulesrc"
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(d / "cache")})
        env.start()
        self.addCleanup(env.stop)

    def gwa(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        argv = [*argv, "--presets-file", str(self.presets_file)]
        if argv[0] in ("apply", "run"):
            argv += ["--rules-file", str(self.rules_file), "--no-reconfigure"]
        # keep "--" (if any) last so the extra flags above stay on the gwa side
        if "--" in argv:
            i = argv.index("--")
            j = argv.index("--presets-file")
            argv = argv[:i] + argv[j:] + argv[i:j]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(argv)
        except SystemExit as e:
            rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def test_save_list_apply_delete(self):
        rc, out, _ = self.gwa("save", "rocketleague", "right", "--width", "2560")
        self.assertEqual(rc, 0, out)
        self.assertIn("Saved preset 'rocketleague'", out)
        self.assertEqual(tomllib.loads(self.presets_file.read_text()),
                         {"rocketleague": {"zone": "right", "width": 2560}})

        rc, out, _ = self.gwa("list")
        self.assertIn("rocketleague  right  2560x1440 at 880,0", out)

        rc, out, _ = self.gwa("apply", "rocketleague")
        self.assertEqual(rc, 0)
        self.assertIn("position=880,0", self.rules_file.read_text())
        self.assertIn("size=2560,1440", self.rules_file.read_text())
        self.assertIn("run rocketleague -- %command%", out)

        rc, out, _ = self.gwa("save", "rocketleague", "left")
        self.assertIn("Updated preset", out)

        rc, out, _ = self.gwa("delete", "rocketleague")
        self.assertEqual(rc, 0)
        self.assertEqual(self.gwa("list")[1].splitlines()[0][:16], "No saved presets")

    def test_cli_flags_override_preset_for_one_run(self):
        self.gwa("save", "rl", "right", "--width", "2560")
        self.gwa("apply", "rl", "--width", "1920")
        self.assertIn("position=1520,0", self.rules_file.read_text())
        self.assertIn("width = 2560", self.presets_file.read_text())  # preset unchanged

    def test_save_copies_existing_preset(self):
        self.gwa("save", "rl", "right", "--width", "2560", "--", "./rl")
        self.gwa("save", "rl2", "rl", "--height", "1080")
        data = tomllib.loads(self.presets_file.read_text())
        self.assertEqual(data["rl2"], {"zone": "right", "width": 2560, "height": 1080, "command": ["./rl"]})

    def test_errors(self):
        rc, _, err = self.gwa("apply", "nope")
        self.assertIn("not a zone", str(rc) + err)
        rc, *_ = self.gwa("save", "left", "right")
        self.assertIn("built-in zone", str(rc))
        rc, *_ = self.gwa("save", "big", "left", "--width", "9999")
        self.assertIn("does not fit", str(rc))
        self.assertFalse(self.presets_file.exists())
        rc, *_ = self.gwa("delete", "ghost")
        self.assertIn("no saved preset", str(rc))

    def test_broken_file_reports_cleanly(self):
        self.presets_file.write_text("[rl]\nzone = right\n")  # unquoted string
        rc, *_ = self.gwa("list")
        self.assertIn(str(self.presets_file), str(rc))

    @mock.patch("gwa.cli.os.execv")
    @mock.patch("gwa.cli.shutil.which", return_value="/usr/bin/gamescope")
    def test_run_options_after_zone_are_not_swallowed(self, _which, execv):
        """Regression: `run left --width 2000 -- ./game` used to put --width into the game command."""
        self.gwa("run", "left", "--width", "2000", "--", "./game", "--fullscreen")
        binary, cmd = execv.call_args.args
        self.assertEqual(binary, "/usr/bin/gamescope")
        self.assertEqual(cmd[cmd.index("--"):], ["--", "./game", "--fullscreen"])
        self.assertEqual(cmd[1:3], ["-W", "2000"])

    @mock.patch("gwa.cli.os.execv")
    @mock.patch("gwa.cli.shutil.which", return_value="/usr/bin/gamescope")
    def test_run_uses_saved_command_unless_given(self, _which, execv):
        self.gwa("save", "spire", "left", "--", "/games/Slay The Spire/run")
        self.gwa("run", "spire")
        self.assertEqual(execv.call_args.args[1][-2:], ["--", "/games/Slay The Spire/run"])
        self.gwa("run", "spire", "--", "steam-cmd", "x")  # e.g. Steam's %command%
        self.assertEqual(execv.call_args.args[1][-3:], ["--", "steam-cmd", "x"])

    def test_run_without_command_errors(self):
        with mock.patch("gwa.cli.shutil.which", return_value="/usr/bin/gamescope"):
            rc, *_ = self.gwa("run", "left")
        self.assertIn("no game command", str(rc))

    def test_command_after_dashdash_rejected_for_other_commands(self):
        rc, _, err = self.gwa("list", "--", "x")
        self.assertEqual(rc, 2)
        self.assertIn("doesn't take a game command", err)


if __name__ == "__main__":
    unittest.main()
