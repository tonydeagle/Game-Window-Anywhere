import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gwa import cli, kwinrules  # noqa: E402
from gwa.zones import Rect  # noqa: E402


class ReloadEnvironment(unittest.TestCase):
    STEAM_ENV = {"LD_PRELOAD": "/steam/gameoverlayrenderer.so", "LD_LIBRARY_PATH": "/steam/runtime",
                 "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "HOME": "/home/me"}

    def test_clean_env_strips_steam_injections_only(self):
        with mock.patch.dict(os.environ, self.STEAM_ENV, clear=True):
            env = kwinrules.clean_env()
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus")

    def test_reconfigure_uses_clean_env(self):
        done = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.dict(os.environ, self.STEAM_ENV, clear=True), \
             mock.patch("gwa.kwinrules.shutil.which", return_value="/usr/bin/qdbus6"), \
             mock.patch("gwa.kwinrules.subprocess.run", return_value=done) as run:
            ok, info = kwinrules.reconfigure_kwin()
        self.assertTrue(ok)
        self.assertEqual(info, "qdbus6 org.kde.KWin /KWin reconfigure")
        self.assertNotIn("LD_PRELOAD", run.call_args.kwargs["env"])

    def test_rule_sets_old_and_new_no_border_keys(self):
        rule = kwinrules.build_rule(Rect(0, 0, 1720, 1440))
        self.assertEqual((rule["noborder"], rule["noborderrule"]), ("true", "2"))
        self.assertEqual((rule["decorationpolicy"], rule["decorationpolicyrule"]), ("none", "2"))


@mock.patch("gwa.cli.os.execv")
@mock.patch("gwa.cli.shutil.which", return_value="/usr/bin/gamescope")
@mock.patch("gwa.cli.time.sleep")
class RunWaitsAndLogs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.dir / "cache")})
        env.start()
        self.addCleanup(env.stop)

    def run_gwa(self, *extra, reload_ok=True):
        result = (True, "qdbus6 org.kde.KWin /KWin reconfigure") if reload_ok else (False, "no qdbus")
        with mock.patch("gwa.cli.kwinrules.reconfigure_kwin", return_value=result), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["run", "left", "--rules-file", str(self.dir / "kwinrulesrc"),
                      "--presets-file", str(self.dir / "p.toml"), *extra, "--", "./game"])

    def log(self):
        return (self.dir / "cache" / "game-window-anywhere" / "run.log").read_text()

    def test_waits_for_kwin_before_starting_gamescope(self, sleep, _which, execv):
        order = []
        sleep.side_effect = lambda s: order.append(("sleep", s))
        execv.side_effect = lambda *a: order.append(("exec",))
        self.run_gwa()
        self.assertEqual(order, [("sleep", cli.RELOAD_SETTLE_SECONDS), ("exec",)])

    def test_no_wait_when_reload_skipped_or_failed(self, sleep, _which, execv):
        self.run_gwa("--no-reconfigure")
        self.run_gwa(reload_ok=False)
        sleep.assert_not_called()
        self.assertEqual(execv.call_count, 2)

    def test_log_records_outcome(self, sleep, _which, execv):
        self.run_gwa()
        self.run_gwa(reload_ok=False)
        log = self.log()
        self.assertIn("run left: zone 1720x1440+0+0", log)
        self.assertIn("KWin reconfigured via qdbus6", log)
        self.assertIn("KWin reload FAILED: no qdbus", log)
        self.assertIn("exec: /usr/bin/gamescope -W 1720", log)


class Redaction(unittest.TestCase):
    def test_heroic_epic_args(self):
        cmd = ["/usr/bin/umu-run", "Launcher.exe", "-AUTH_LOGIN=unused", "-AUTH_PASSWORD=83125338c9e0",
               "-AUTH_TYPE=exchangecode", "-epicapp=Sugar", "--api-token=abc", "client_secret=x",
               "/games/Slay the Spire 2/run"]
        self.assertEqual(cli.redact(cmd), [
            "/usr/bin/umu-run", "Launcher.exe", "-AUTH_LOGIN=unused", "-AUTH_PASSWORD=<redacted>",
            "-AUTH_TYPE=exchangecode", "-epicapp=Sugar", "--api-token=<redacted>",
            "client_secret=<redacted>", "/games/Slay the Spire 2/run"])

    @mock.patch("gwa.cli.os.execv")
    @mock.patch("gwa.cli.shutil.which", return_value="/usr/bin/gamescope")
    def test_secret_not_in_log_or_output_but_still_passed_to_game(self, _which, execv):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"XDG_CACHE_HOME": d}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                cli.main(["run", "left", "--rules-file", f"{d}/k", "--presets-file", f"{d}/p.toml",
                          "--no-reconfigure", "--", "game.exe", "-AUTH_PASSWORD=s3cret"])
            log = Path(d, "game-window-anywhere", "run.log").read_text()
        self.assertNotIn("s3cret", log + out.getvalue())
        self.assertIn("-AUTH_PASSWORD=<redacted>", log)
        self.assertEqual(execv.call_args.args[1][-1], "-AUTH_PASSWORD=s3cret")


if __name__ == "__main__":
    unittest.main()
