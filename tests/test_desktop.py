import configparser
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gwa import cli, desktop  # noqa: E402


class ExecQuoting(unittest.TestCase):
    def test_plain_path_unquoted(self):
        self.assertEqual(desktop.exec_arg("/home/tony/game-window-anywhere/gwa"),
                         "/home/tony/game-window-anywhere/gwa")

    def test_spaces_and_specials(self):
        self.assertEqual(desktop.exec_arg("/home/t/My Games/gwa"), '"/home/t/My Games/gwa"')
        self.assertEqual(desktop.exec_arg("/a/$x`y/gwa"), '"/a/\\\\$x\\\\`y/gwa"')
        self.assertEqual(desktop.exec_arg("/a/100%/gwa"), "/a/100%%/gwa")


class InstallRemove(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        p = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        r = mock.patch("gwa.desktop.refresh_menu", return_value="kbuildsycoca6")
        r.start()
        self.addCleanup(r.stop)

    def gwa(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
             mock.patch("gwa.core.gwa_executable", return_value="/home/t/My Games/gwa"):
            rc = cli.main(list(argv))
        return rc, out.getvalue()

    def test_install_then_remove(self):
        rc, out = self.gwa("install-desktop")
        self.assertEqual(rc, 0)
        entry = self.home / "applications" / "game-window-anywhere.desktop"
        icon = self.home / "icons/hicolor/scalable/apps/game-window-anywhere.svg"
        self.assertTrue(icon.read_text().startswith("<svg"))
        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str
        cp.read(entry)
        d = cp["Desktop Entry"]
        self.assertEqual(d["Exec"], '"/home/t/My Games/gwa" gui')
        self.assertEqual(d["Icon"], "game-window-anywhere")
        self.assertEqual(d["Type"], "Application")
        self.assertIn("Plasma's app menu refreshed", out)

        rc, out = self.gwa("install-desktop")  # idempotent
        self.assertEqual(rc, 0)

        rc, out = self.gwa("install-desktop", "--remove")
        self.assertFalse(entry.exists())
        self.assertFalse(icon.exists())
        rc, out = self.gwa("install-desktop", "--remove")
        self.assertIn("nothing to do", out)

    def test_icon_ships_with_package(self):
        self.assertTrue(desktop.ICON_SOURCE.is_file())


if __name__ == "__main__":
    unittest.main()
