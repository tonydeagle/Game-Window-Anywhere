import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gwa import core, kwinrules, monitors, taskbar  # noqa: E402
from gwa.monitors import Live, Monitor, Panel  # noqa: E402
from gwa.presets import Settings  # noqa: E402
from gwa.zones import Rect  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "kscreen-ultrawide.json"
BOTTOM_46 = Panel(index=0, location="bottom", thickness=46, hiding="none", screen=0)
ULTRAWIDE = Monitor("DP-1", 3440, 1440, refresh=240.0, primary=True)


class KScreenParsing(unittest.TestCase):
    def test_real_ultrawide_output(self):
        """kscreen-doctor -j from the author's PC (Plasma 6, 3440x1440 @ 240 Hz)."""
        [m] = monitors.parse_kscreen(FIXTURE.read_text())
        self.assertEqual((m.name, m.size, (m.x, m.y), m.scale, m.primary), ("DP-1", (3440, 1440), (0, 0), 1.0, True))
        self.assertEqual(round(m.refresh), 240)
        self.assertEqual(m.label(), "DP-1 · 3440 × 1440 · 240 Hz")

    def output(self, **kw):
        base = json.loads(FIXTURE.read_text())["outputs"][0]
        return {**base, **kw}

    def test_rotation_disabled_and_second_monitor(self):
        doc = {"outputs": [
            self.output(),
            self.output(name="HDMI-A-1", priority=2, pos={"x": 3440, "y": 0}, rotation=2, scale=1.25,
                        currentModeId="6"),       # 2560x1440 rotated to portrait
            self.output(name="DP-2", enabled=False),
            self.output(name="DP-3", connected=False),
        ]}
        ms = monitors.parse_kscreen(json.dumps(doc))
        self.assertEqual([m.name for m in ms], ["DP-1", "HDMI-A-1"])
        side = ms[1]
        self.assertEqual((side.size, side.x, side.primary), ((1440, 2560), 3440, False))
        self.assertEqual(side.logical, (3440, 0, 1152, 2048))
        live = Live(ms)
        self.assertEqual(live.find("primary").name, "DP-1")
        self.assertEqual(live.find("HDMI-A-1"), side)
        self.assertIsNone(live.find("DP-9"))

    def test_first_monitor_is_primary_when_none_marked(self):
        ms = monitors.parse_kscreen(json.dumps({"outputs": [self.output(priority=0)]}))
        self.assertTrue(ms[0].primary)


class Panels(unittest.TestCase):
    def test_parse_handles_missing_geometry(self):
        text = json.dumps([{"index": 0, "location": "bottom", "thickness": 46, "hiding": "none",
                            "screen": 0, "geometry": [None, None, None, None]},
                           {"index": 1, "location": "left", "thickness": 60, "hiding": "autohide",
                            "screen": 0, "geometry": [0, 0, 3440, 1440]}])
        a, b = monitors.parse_panels(text)
        self.assertIsNone(a.geometry)
        self.assertEqual(b.geometry, (0, 0, 3440, 1440))
        self.assertTrue(a.always_visible)
        self.assertFalse(b.always_visible)

    def test_insets_scale_and_ignore_hidden_panels(self):
        panels = [BOTTOM_46, Panel(1, "top", 30, "autohide"), Panel(2, "left", 40, "none")]
        self.assertEqual(monitors.insets(panels, 1.0), (40, 0, 0, 46))
        self.assertEqual(monitors.insets(panels, 1.5), (60, 0, 0, 69))

    def test_panels_on_by_geometry_with_two_monitors(self):
        side = Monitor("HDMI-A-1", 1920, 1080, x=3440)
        p_main = Panel(0, "bottom", 46, "none", 0, (0, 0, 3440, 1440))
        p_side = Panel(1, "top", 30, "none", 1, (3440, 0, 1920, 1080))
        live = Live([ULTRAWIDE, side], [p_main, p_side])
        self.assertEqual(live.panels_on(ULTRAWIDE), [p_main])
        self.assertEqual(live.panels_on(side), [p_side])
        self.assertEqual(Live([ULTRAWIDE], [p_main, p_side]).panels_on(ULTRAWIDE), [p_main, p_side])


class PlanWithDetection(unittest.TestCase):
    def test_fit_above_bottom_taskbar(self):
        live = Live([ULTRAWIDE], [BOTTOM_46])
        p = core.plan(Settings(zone="left", taskbar="fit"), live)
        self.assertEqual(p.zone, Rect(0, 0, 1720, 1394))
        self.assertEqual(p.gamescope_args[:8], ["-W", "1720", "-H", "1394", "-w", "1720", "-h", "1394"])
        right = core.plan(Settings(zone="right", width=2560, taskbar="fit"), live)
        self.assertEqual(right.zone, Rect(880, 0, 2560, 1394))

    def test_fit_with_top_panel_and_scale(self):
        live = Live([replace(ULTRAWIDE, scale=1.25)], [Panel(0, "top", 40, "none")])
        p = core.plan(Settings(zone="left", monitor="primary", taskbar="fit"), live)
        self.assertEqual(p.zone, Rect(0, 50, 1720, 1390))
        self.assertEqual(p.kwin_rect, Rect(0, 40, 1376, 1112))

    def test_fit_explains_when_zone_too_tall(self):
        with self.assertRaisesRegex(ValueError, "taskbar takes 46 px; usable area is 3440x1394"):
            core.plan(Settings(zone="left", height=1440, taskbar="fit"), Live([ULTRAWIDE], [BOTTOM_46]))

    def test_fit_without_detection_warns_and_uses_full_height(self):
        p = core.plan(Settings(zone="left", taskbar="fit"), Live(panel_error="plasmashell: not running"))
        self.assertEqual(p.zone.h, 1440)
        self.assertIn("couldn't detect the taskbar", p.warnings[0])

    def test_follow_monitor(self):
        side = Monitor("HDMI-A-1", 2560, 1440, x=3440, y=0, scale=1.0)
        live = Live([ULTRAWIDE, side])
        p = core.plan(Settings(zone="right", monitor="HDMI-A-1"), live)
        self.assertEqual(p.zone, Rect(1280, 0, 1280, 1440))
        self.assertEqual(p.kwin_rect, Rect(4720, 0, 1280, 1440))
        self.assertEqual(p.monitor, side)

    def test_missing_monitor_falls_back_with_warning(self):
        p = core.plan(Settings(zone="left", monitor="DP-9"), Live([ULTRAWIDE]))
        self.assertEqual(p.zone, Rect(0, 0, 1720, 1440))
        self.assertIn("monitor 'DP-9' not connected (found: DP-1)", p.warnings[0])

    def test_cover_adds_layer_rule(self):
        rule = kwinrules.build_rule(Rect(0, 0, 1, 1), above_panels=True)
        self.assertEqual((rule["layer"], rule["layerrule"]), ("fullscreen", "2"))
        self.assertNotIn("layer", kwinrules.build_rule(Rect(0, 0, 1, 1)))


class TaskbarState(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.calls = []
        self.set = self.calls.append

    def test_two_games_restore_once_after_last(self):
        with mock.patch("gwa.taskbar._alive", return_value=True):  # fake pids 111/222 "running"
            self.assertEqual(taskbar.begin([BOTTOM_46], 111, self.set), [0])
            self.assertEqual(taskbar.begin([replace(BOTTOM_46, hiding="autohide")], 222, self.set), [])
            self.assertEqual(taskbar.end(111, self.set), {})
            self.assertEqual(taskbar.end(222, self.set), {0: "none"})
        self.assertEqual(self.calls, [{0: "autohide"}, {0: "none"}])
        self.assertFalse(taskbar.state_path().exists())

    def test_killed_gwa_is_cleaned_up(self):
        with mock.patch("gwa.taskbar._alive", return_value=True):
            taskbar.begin([BOTTOM_46], 111, self.set)
            self.assertEqual(taskbar.restore(set_hiding=self.set), {})       # game still running
        with mock.patch("gwa.taskbar._alive", return_value=False):
            self.assertEqual(taskbar.restore(set_hiding=self.set), {0: "none"})  # gwa was killed

    def test_force_restore(self):
        with mock.patch("gwa.taskbar._alive", return_value=True):
            taskbar.begin([BOTTOM_46], 111, self.set)
            self.assertEqual(taskbar.restore(force=True, set_hiding=self.set), {0: "none"})

    def test_leaves_hidden_panels_alone(self):
        self.assertEqual(taskbar.begin([Panel(0, "bottom", 46, "autohide")], 111, self.set), [])
        self.assertEqual(self.calls, [])


@unittest.skipIf(sys.platform != "linux", "uses executable fake tools")
class EndToEndWithFakeKDE(unittest.TestCase):
    """Runs gwa against stand-ins for kscreen-doctor, qdbus6 and gamescope (tests/fakes)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        bin_dir = self.d / "bin"
        shutil.copytree(ROOT / "tests" / "fakes", bin_dir)
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        self.panels = self.d / "panels.json"
        self.panels.write_text(json.dumps([{"location": "bottom", "thickness": 46, "hiding": "none",
                                            "screen": 0, "geometry": None}]))
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FAKE_KSCREEN_JSON": str(FIXTURE), "FAKE_PANELS": str(self.panels),
                    "FAKE_GAMESCOPE_OUT": str(self.d / "gamescope.json"),
                    "XDG_CACHE_HOME": str(self.d / "cache"), "XDG_CONFIG_HOME": str(self.d / "config")}
        for k in ("LD_PRELOAD", "LD_LIBRARY_PATH"):
            self.env.pop(k, None)

    def gwa(self, *args, rc=0):
        res = subprocess.run([sys.executable, str(ROOT / "gwa"), *args], env=self.env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, rc, res.stdout + res.stderr)
        return res.stdout + res.stderr

    def test_monitors_command(self):
        out = self.gwa("monitors")
        self.assertIn("DP-1 · 3440 × 1440 · 240 Hz  at 0,0  (primary)", out)
        self.assertIn("bottom  46 px, always visible", out)

    def test_apply_fit_writes_shorter_rule(self):
        self.gwa("apply", "left", "--monitor", "primary", "--taskbar", "fit", "--no-reconfigure")
        rule = (self.d / "config" / "kwinrulesrc").read_text()
        self.assertIn("size=1720,1394", rule)
        self.assertIn("position=0,0", rule)

    def test_apply_cover_writes_layer(self):
        self.gwa("apply", "right", "--taskbar", "cover", "--no-reconfigure")
        self.assertIn("layer=fullscreen", (self.d / "config" / "kwinrulesrc").read_text())

    def test_run_autohide_hides_during_game_and_restores_after(self):
        self.env["FAKE_GAMESCOPE_RC"] = "3"
        self.gwa("run", "left", "--taskbar", "autohide", "--no-reconfigure", "--", "game.exe", rc=3)
        seen = json.loads((self.d / "gamescope.json").read_text())
        self.assertEqual(seen["panels_during_game"][0]["hiding"], "autohide")
        self.assertEqual(seen["args"][-2:], ["--", "game.exe"])
        self.assertEqual(json.loads(self.panels.read_text())[0]["hiding"], "none")  # restored
        log = (self.d / "cache" / "game-window-anywhere" / "run.log").read_text()
        self.assertIn("auto-hidden panel(s) 0 until the game exits", log)
        self.assertIn("game exited (3); taskbar restored", log)
        self.assertIn("Nothing to restore.", self.gwa("taskbar", "restore"))

    def test_run_without_autohide_still_execs(self):
        self.gwa("run", "left", "--no-reconfigure", "--", "game.exe")
        self.assertEqual(json.loads((self.d / "gamescope.json").read_text())["panels_during_game"][0]["hiding"], "none")
        self.assertFalse((self.d / "panels.json.log").exists())  # plasmashell never contacted


if __name__ == "__main__":
    unittest.main()
