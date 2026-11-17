import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # the CLI doesn't need Qt; skip GUI tests where it isn't installed
    QApplication = None

if QApplication is not None:
    from gwa import gui, presets
    from gwa.presets import Settings
    from gwa.zones import Rect


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        self.pf, self.rules = d / "presets.toml", d / "kwinrulesrc"
        presets.save({"rocketleague": Settings(zone="right", width=2560),
                      "spire": Settings(zone="left")}, self.pf)
        self.original = self.pf.read_text()

    def window(self):
        w = gui.MainWindow(self.pf, self.rules)
        self.addCleanup(w.deleteLater)
        return w

    def close(self, w, answer):
        ev = QCloseEvent()
        with mock.patch.object(w, "ask_unsaved", return_value=answer) as ask:
            w.closeEvent(ev)
        return ev.isAccepted(), ask.called

    def select_size(self, w, size):
        lst = w.editor.sizes
        for i in range(lst.count()):
            if lst.item(i).data(gui.Qt.UserRole) == size:
                lst.setCurrentRow(i)
                return
        raise AssertionError(f"{size} not in list")

    # ---- loading never counts as a change

    def test_open_and_close_without_edits_is_silent(self):
        w = self.window()
        self.assertEqual([w.list.item(i).text() for i in range(w.list.count())], ["rocketleague", "spire"])
        w.list.setCurrentRow(1)
        self.assertFalse(w.is_dirty())
        accepted, asked = self.close(w, QMessageBox.Cancel)
        self.assertTrue(accepted)
        self.assertFalse(asked)
        self.assertEqual(self.pf.read_text(), self.original)

    def test_round_trip_of_every_kind_of_preset_is_not_dirty(self):
        presets.save({
            "a": Settings(zone="custom", rect=Rect(700, 170, 2000, 1100)),
            "b": Settings(zone="center", width=2560, height=1080, render=(1920, 810)),
            "c": Settings(zone="right", width=1147, gamescope_args="-r 144", command=("/x y/run", "-f")),
            "d": Settings(zone="left", screen=(2560, 1440), origin=(-2560, 0), scale=1.25, wmclass="gs"),
        }, self.pf)
        w = self.window()
        for row in range(4):
            w.list.setCurrentRow(row)
            self.assertFalse(w.is_dirty(), w.change_summary())

    # ---- editing + confirm on exit

    def test_edit_marks_dirty(self):
        w = self.window()
        self.select_size(w, (1920, 1080))
        self.assertTrue(w.is_dirty())
        self.assertEqual(w.list.item(0).text(), "rocketleague  •")
        self.assertTrue(w.windowTitle().startswith("*"))
        self.assertEqual(w.change_summary(), ["rocketleague: changed"])
        self.assertEqual(w.preview.zone, Rect(1520, 180, 1920, 1080))  # centred vertically

    def test_close_cancel_keeps_window_and_changes(self):
        w = self.window()
        self.select_size(w, (1920, 1080))
        accepted, asked = self.close(w, QMessageBox.Cancel)
        self.assertTrue(asked)
        self.assertFalse(accepted)
        self.assertTrue(w.is_dirty())
        self.assertEqual(self.pf.read_text(), self.original)

    def test_close_discard_leaves_file_alone(self):
        w = self.window()
        self.select_size(w, (1920, 1080))
        accepted, _ = self.close(w, QMessageBox.Discard)
        self.assertTrue(accepted)
        self.assertEqual(self.pf.read_text(), self.original)

    def test_close_save_writes_file(self):
        w = self.window()
        self.select_size(w, (1920, 1080))
        accepted, _ = self.close(w, QMessageBox.Save)
        self.assertTrue(accepted)
        data = tomllib.loads(self.pf.read_text())
        self.assertEqual(data["rocketleague"], {"zone": "right", "width": 1920, "height": 1080})
        self.assertEqual(data["spire"], {"zone": "left"})

    def test_close_save_that_fails_keeps_window_open(self):
        w = self.window()
        w.editor.name.setText("bad name!")
        w.editor.name.textEdited.emit("bad name!")
        accepted, _ = self.close(w, QMessageBox.Save)
        self.assertFalse(accepted)
        self.assertEqual(self.pf.read_text(), self.original)

    # ---- custom sizes / positions

    def test_custom_size_and_position(self):
        w = self.window()
        ed = w.editor
        ed.pos_buttons["custom"].setChecked(True)
        ed.sizes.setCurrentRow(ed.sizes.count() - 1)  # Custom size…
        self.assertTrue(ed.custom_size.isVisibleTo(ed))
        ed.custom_w.setValue(2000)
        ed.custom_h.setValue(1100)
        ed.pos_x.setValue(700)
        ed.pos_y.setValue(170)
        self.assertTrue(w.save())
        self.assertEqual(tomllib.loads(self.pf.read_text())["rocketleague"],
                         {"zone": "custom", "rect": "700,170,2000,1100"})

    def test_non_standard_size_opens_as_custom(self):
        presets.save({"odd": Settings(zone="right", width=1999, height=1001)}, self.pf)
        w = self.window()
        ed = w.editor
        self.assertIsNone(ed.sizes.currentItem().data(gui.Qt.UserRole))
        self.assertEqual((ed.custom_w.value(), ed.custom_h.value()), (1999, 1001))
        self.assertFalse(w.is_dirty())

    def test_custom_position_cannot_leave_screen(self):
        w = self.window()
        ed = w.editor
        ed.pos_buttons["custom"].setChecked(True)
        self.assertEqual(ed.pos_x.maximum(), 3440 - 2560)

    def test_size_list_follows_monitor_resolution(self):
        w = self.window()
        w.editor.screen_w.setValue(1920)
        w.editor.screen_h.setValue(1080)
        sizes = [w.editor.sizes.item(i).data(gui.Qt.UserRole) for i in range(w.editor.sizes.count())]
        self.assertNotIn((2560, 1440), sizes)
        self.assertIn((960, 1080), sizes)

    # ---- names, new, delete

    def test_invalid_and_duplicate_names_block_save(self):
        w = self.window()
        for bad in ("left", "has space", "spire"):
            w.editor.name.setText(bad)
            w.editor.name.textEdited.emit(bad)
            self.assertTrue(w.editor.name_error.text(), bad)
            self.assertFalse(w.save(), bad)
        self.assertEqual(self.pf.read_text(), self.original)

    def test_rename(self):
        w = self.window()
        w.editor.name.setText("rl")
        w.editor.name.textEdited.emit("rl")
        self.assertEqual(w.change_summary(), ["rocketleague: renamed to rl"])
        self.assertTrue(w.save())
        self.assertEqual(sorted(tomllib.loads(self.pf.read_text())), ["rl", "spire"])

    def test_new_and_duplicate(self):
        w = self.window()
        w.new_preset()
        w.duplicate_preset()
        names = [e.name for e in w.entries]
        self.assertEqual(names, ["rocketleague", "spire", "new-game", "new-game-copy"])
        self.assertTrue(w.save())
        self.assertEqual(len(tomllib.loads(self.pf.read_text())), 4)

    def test_delete_asks_and_is_pending_until_save(self):
        w = self.window()
        with mock.patch.object(w, "confirm", return_value=QMessageBox.No):
            w.delete_preset()
        self.assertEqual(len(w.entries), 2)
        with mock.patch.object(w, "confirm", return_value=QMessageBox.Yes):
            w.delete_preset()
        self.assertEqual([e.name for e in w.entries], ["spire"])
        self.assertIn("rocketleague", tomllib.loads(self.pf.read_text()))
        self.assertEqual(w.change_summary(), ["rocketleague: deleted"])
        self.assertTrue(w.save())
        self.assertEqual(list(tomllib.loads(self.pf.read_text())), ["spire"])

    def test_revert(self):
        w = self.window()
        self.select_size(w, (1920, 1080))
        with mock.patch.object(w, "confirm", return_value=QMessageBox.Yes):
            w.revert()
        self.assertFalse(w.is_dirty())

    # ---- safety + KWin

    def test_unreadable_presets_file_is_never_overwritten(self):
        self.pf.write_text("[rl]\nzone = right\n")  # invalid TOML
        w = self.window()
        self.assertFalse(w.btn_save.isEnabled())
        w.new_preset()
        self.assertFalse(w.save())
        self.assertEqual(self.pf.read_text(), "[rl]\nzone = right\n")

    def test_apply_now_writes_kwin_rule(self):
        w = self.window()
        with mock.patch("gwa.gui.kwinrules.reconfigure_kwin", return_value=(True, "qdbus6")):
            w.apply_now()
        self.assertIn("position=880,0", self.rules.read_text())
        self.assertIn("is active", w.status.text())

    def test_launch_options_follow_name(self):
        w = self.window()
        self.assertTrue(w.launch.steam.text().endswith("run rocketleague -- %command%"))
        self.assertEqual(w.launch.heroic_args.text(), "run rocketleague --")


if __name__ == "__main__":
    unittest.main()
