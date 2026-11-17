import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gwa import cli, gamescope, kwinrules  # noqa: E402
from gwa.zones import Rect, compute_zone, parse_rect  # noqa: E402

EXISTING = """\
[$Version]
update_info=kwinrules.upd:replace-placement-string-to-enum

[General]
count=1
rules=aaaa-bbbb

[aaaa-bbbb]
Description=Firefox on desktop 2
wmclass=firefox
wmclassmatch=1
"""


class Zones(unittest.TestCase):
    def test_presets(self):
        self.assertEqual(compute_zone("left"), Rect(0, 0, 1720, 1440))
        self.assertEqual(compute_zone("right"), Rect(1720, 0, 1720, 1440))
        self.assertEqual(compute_zone("right", width=2560), Rect(880, 0, 2560, 1440))
        self.assertEqual(compute_zone("center", width=2560, height=1080), Rect(440, 180, 2560, 1080))

    def test_custom(self):
        self.assertEqual(compute_zone("custom", rect=parse_rect("10,20,800,600")), Rect(10, 20, 800, 600))
        self.assertEqual(parse_rect("800x600+10+20"), Rect(10, 20, 800, 600))
        with self.assertRaises(ValueError):
            compute_zone("custom")

    def test_too_wide(self):
        with self.assertRaises(ValueError):
            compute_zone("left", width=4000)

    def test_scale(self):
        self.assertEqual(Rect(1720, 0, 1720, 1440).scaled(1.25), Rect(1376, 0, 1376, 1152))


class Gamescope(unittest.TestCase):
    def test_steam(self):
        args = gamescope.gamescope_args(1720, 1440)
        self.assertEqual(
            gamescope.steam_launch_option(args),
            "gamescope -W 1720 -H 1440 -w 1720 -h 1440 -b --force-grab-cursor -- %command%",
        )

    def test_render_and_extra(self):
        args = gamescope.gamescope_args(1720, 1440, (1280, 1080), ["-r", "144"])
        self.assertEqual(args[4:8], ["-w", "1280", "-h", "1080"])
        self.assertEqual(args[-2:], ["-r", "144"])


class KConfigTests(unittest.TestCase):
    def test_roundtrip_untouched(self):
        self.assertEqual(kwinrules.KConfig(EXISTING).dumps(), EXISTING)

    def test_upsert_preserves_and_is_idempotent(self):
        cfg = kwinrules.KConfig(EXISTING)
        kwinrules.upsert_rule(cfg, kwinrules.build_rule(Rect(0, 0, 1720, 1440)))
        kwinrules.upsert_rule(cfg, kwinrules.build_rule(Rect(1720, 0, 1720, 1440)))
        out = kwinrules.KConfig(cfg.dumps())
        self.assertEqual(out.get("General", "count"), "2")
        self.assertEqual(out.get("General", "rules"), f"aaaa-bbbb,{kwinrules.RULE_ID}")
        self.assertEqual(out.get(kwinrules.RULE_ID, "position"), "1720,0")
        self.assertEqual(out.get(kwinrules.RULE_ID, "sizerule"), "2")
        self.assertEqual(out.get("aaaa-bbbb", "wmclass"), "firefox")
        self.assertEqual(out.get("$Version", "update_info"), "kwinrules.upd:replace-placement-string-to-enum")
        self.assertEqual(cfg.dumps().count(f"[{kwinrules.RULE_ID}]"), 1)

    def test_delete(self):
        cfg = kwinrules.KConfig(EXISTING)
        kwinrules.upsert_rule(cfg, kwinrules.build_rule(Rect(0, 0, 1, 1)))
        self.assertTrue(kwinrules.delete_rule(cfg))
        self.assertEqual(cfg.get("General", "rules"), "aaaa-bbbb")
        self.assertEqual(cfg.get("General", "count"), "1")
        self.assertFalse(cfg.has_group(kwinrules.RULE_ID))

    def test_empty_file(self):
        cfg = kwinrules.KConfig("")
        kwinrules.upsert_rule(cfg, kwinrules.build_rule(Rect(0, 0, 1720, 1440)))
        text = cfg.dumps()
        self.assertTrue(text.startswith("[General]\ncount=1\nrules="))

    def test_conflict_detection(self):
        cfg = kwinrules.KConfig(EXISTING.replace("wmclass=firefox", "wmclass=gamescope"))
        self.assertEqual(kwinrules.other_gamescope_rules(cfg), ["Firefox on desktop 2"])


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(list(argv))
        return rc, buf.getvalue()

    def test_apply_status_remove(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "kwinrulesrc"
            path.write_text(EXISTING)
            rc, out = self.run_cli("apply", "right", "--rules-file", str(path), "--no-reconfigure")
            self.assertEqual(rc, 0)
            self.assertIn("-- %command%", out)
            self.assertIn("position=1720,0", path.read_text())
            self.assertTrue((Path(d) / "kwinrulesrc.gwa-backup").exists())

            rc, out = self.run_cli("status", "--rules-file", str(path))
            self.assertEqual(rc, 0)
            self.assertIn("size=1720,1440", out)

            rc, _ = self.run_cli("remove", "--rules-file", str(path), "--no-reconfigure")
            self.assertEqual(path.read_text(), EXISTING)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "kwinrulesrc"
            _, out = self.run_cli("apply", "left", "--dry-run", "--rules-file", str(path))
            self.assertFalse(path.exists())
            self.assertIn("position=0,0", out)

    def test_multimonitor_origin(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "kwinrulesrc"
            self.run_cli("apply", "left", "--origin", "1920,0", "--rules-file", str(path), "--no-reconfigure")
            self.assertIn("position=1920,0", path.read_text())


if __name__ == "__main__":
    unittest.main()
