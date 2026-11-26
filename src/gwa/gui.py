"""Game Window Anywhere — a small Qt GUI for editing per-game presets.

Edits are kept in memory until Save; closing with unsaved changes asks first.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)

from . import __version__, core, desktop, kwinrules, monitors, presets, taskbar
from .desktop import DESKTOP_ID
from .monitors import Live, Monitor
from .presets import Settings
from .zones import Rect, compute_zone, size_choices

# ---------------------------------------------------------------- theme

C = {
    "bg": "#0c1626",        # window
    "panel": "#132238",     # cards / sidebar
    "panel2": "#1a2d49",    # inputs
    "border": "#2a4670",
    "accent": "#3b82f6",
    "accent_hi": "#60a5fa",
    "accent_lo": "#1d4ed8",
    "text": "#e8f0fb",
    "muted": "#a9bdd6",
    "error": "#fca5a5",
    "ok": "#86efac",
    "warn": "#fcd34d",
}

ASSETS = Path(__file__).resolve().parent / "assets"
_UP, _DOWN = (ASSETS / "arrow-up.svg").as_posix(), (ASSETS / "arrow-down.svg").as_posix()
_RADIO_ON, _RADIO_OFF = (ASSETS / "radio-on.svg").as_posix(), (ASSETS / "radio-off.svg").as_posix()

STYLE = f"""
QWidget {{ color: {C['text']}; }}
QMainWindow, #central {{ background: {C['bg']}; }}
QScrollArea, #scrollBody {{ background: {C['bg']}; border: none; }}
#sidebar, *[class="card"] {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px; }}
#appTitle {{ font-size: 18pt; font-weight: 600; }}
#appSubtitle, *[class="desc"] {{ color: {C['muted']}; }}
*[class="cardTitle"] {{ font-size: 12.5pt; font-weight: 600; color: {C['accent_hi']}; }}
*[class="fieldTitle"] {{ font-weight: 600; }}
*[class="error"] {{ color: {C['error']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 6px;
    padding: 5px 8px; selection-background-color: {C['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {C['accent_hi']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: #5d7391; border-color: #22385a; }}
QSpinBox, QDoubleSpinBox {{ padding: 5px 4px 5px 8px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: padding; width: 24px; background: {C['panel']};
    border-left: 1px solid {C['border']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right; border-top-right-radius: 5px; border-bottom: 1px solid {C['border']};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right; border-bottom-right-radius: 5px;
}}
QSpinBox::up-button:disabled, QSpinBox::down-button:disabled,
QDoubleSpinBox::up-button:disabled, QDoubleSpinBox::down-button:disabled {{
    background: transparent; border-color: #22385a;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {C['border']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{_UP}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{_DOWN}"); width: 10px; height: 10px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled,
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: none; }}
QLineEdit[readOnly="true"] {{ color: {C['muted']}; }}
QLineEdit[invalid="true"] {{ border-color: {C['error']}; }}
QListWidget {{
    background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 4px;
    outline: none;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 5px; }}
QListWidget::item:hover {{ background: {C['border']}; }}
QListWidget::item:selected {{ background: {C['accent']}; color: white; }}
#sidebar QListWidget {{ background: transparent; border: none; }}
QPushButton, QToolButton {{
    background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {C['accent_hi']}; }}
QPushButton:pressed {{ background: {C['border']}; }}
QPushButton:disabled {{ color: #5d7391; border-color: #22385a; }}
QPushButton:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; color: white; }}
QPushButton[class="primary"] {{ background: {C['accent']}; border-color: {C['accent_hi']}; color: white; font-weight: 600; }}
QPushButton[class="primary"]:hover {{ background: {C['accent_hi']}; }}
QPushButton[class="primary"]:disabled {{ background: #22385a; color: #6b84a5; }}
QToolButton {{ border: none; background: transparent; color: {C['accent_hi']}; font-weight: 600; padding: 2px 0; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QRadioButton {{ font-weight: 600; }}
QRadioButton::indicator {{ width: 16px; height: 16px; image: url("{_RADIO_OFF}"); }}
QRadioButton::indicator:checked {{ image: url("{_RADIO_ON}"); }}
QComboBox {{
    background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 6px;
    padding: 5px 10px; min-width: 260px;
}}
QComboBox:hover, QComboBox:focus {{ border-color: {C['accent_hi']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; }}
QComboBox::down-arrow {{ image: url("{_DOWN}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: {C['panel2']}; border: 1px solid {C['border']};
    selection-background-color: {C['accent']}; outline: none; padding: 4px; }}
#previewBar {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {C['border']}; background: {C['panel2']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
#footer {{ background: {C['panel']}; border-top: 1px solid {C['border']}; }}
QMessageBox {{ background: {C['panel']}; }}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['border']}; }}
"""


def _cls(widget: QWidget, name: str) -> QWidget:
    widget.setProperty("class", name)
    return widget


def _label(text: str, cls: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if cls:
        _cls(lab, cls)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def _spin(lo: int, hi: int, suffix: str = " px") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSuffix(suffix)
    s.setAccelerated(True)
    s.setMinimumWidth(110)
    return s


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        _cls(self, "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 14, 18, 18)
        self.body.setSpacing(14)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(title, "cardTitle"))
        if subtitle:
            head.addWidget(_label(subtitle, "desc", wrap=True))
        self.body.addLayout(head)

    def field(self, title: str, description: str, *widgets: QWidget | QHBoxLayout) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(_label(title, "fieldTitle"))
        if description:
            lay.addWidget(_label(description, "desc", wrap=True))
        lay.addSpacing(2)
        for w in widgets:
            lay.addLayout(w) if isinstance(w, QHBoxLayout) else lay.addWidget(w)
        self.body.addWidget(box)
        return box


def _row(*widgets, stretch: bool = True) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(8)
    for w in widgets:
        lay.addWidget(_label(w, "desc") if isinstance(w, str) else w)
    if stretch:
        lay.addStretch(1)
    return lay


# ---------------------------------------------------------------- monitor preview

class MonitorPreview(QWidget):
    """Draws the monitor with the zone highlighted."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.screen = (3440, 1440)
        self.zone: Rect | None = None
        self.error = ""
        self.panels: tuple[int, int, int, int] = (0, 0, 0, 0)  # always-visible panel insets
        self.taskbar = "leave"
        self.caption = ""

    def show_zone(self, screen: tuple[int, int], zone: Rect | None, error: str = "",
                  panels: tuple[int, int, int, int] = (0, 0, 0, 0), taskbar_mode: str = "leave",
                  caption: str = "") -> None:
        self.screen, self.zone, self.error = screen, zone, error
        self.panels, self.taskbar, self.caption = panels, taskbar_mode, caption
        self.update()

    def _draw_panels(self, p: QPainter, mx: float, my: float, mw: float, mh: float, k: float,
                     faded: bool) -> None:
        # Panels are thin next to a 1440 px monitor; keep them visible in the small preview.
        l, t, r, b = (max(v * k, 6) if v else 0 for v in self.panels)
        strips = [QRectF(mx, my + mh - b, mw, b), QRectF(mx, my, mw, t),
                  QRectF(mx, my, l, mh), QRectF(mx + mw - r, my, r, mh)]
        colour = QColor("#c7d6ea")
        colour.setAlpha(70 if faded else 200)
        p.setPen(Qt.NoPen if not faded else QPen(QColor(C["muted"]), 1, Qt.DashLine))
        p.setBrush(colour)
        for strip in strips:
            if strip.width() > 0 and strip.height() > 0:
                p.drawRect(strip.adjusted(1, 1, -1, -1))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sw, sh = self.screen
        avail_w, avail_h = self.width() - 24, self.height() - 34
        k = min(avail_w / sw, avail_h / sh)
        mw, mh = sw * k, sh * k
        mx, my = (self.width() - mw) / 2, 6
        monitor = QRectF(mx, my, mw, mh)

        p.setPen(QPen(QColor(C["border"]), 2))
        p.setBrush(QColor("#08101c"))
        p.drawRoundedRect(monitor, 6, 6)

        # fit/autohide: panels drawn first (no overlap / hidden while playing).
        if self.taskbar in ("fit", "autohide"):
            self._draw_panels(p, mx, my, mw, mh, k, faded=self.taskbar == "autohide")

        if self.zone is not None:
            z = self.zone
            zr = QRectF(mx + z.x * k, my + z.y * k, z.w * k, z.h * k).adjusted(1.5, 1.5, -1.5, -1.5)
            fill = QColor(C["accent"])
            fill.setAlpha(200)
            p.setPen(QPen(QColor(C["accent_hi"]), 2))
            p.setBrush(fill)
            p.drawRoundedRect(zr, 4, 4)
            p.setPen(QColor("white"))
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            p.drawText(zr, Qt.AlignCenter, f"{z.w} × {z.h}\nat {z.x}, {z.y}")

        if self.taskbar == "leave":  # an always-visible panel is drawn over the game
            self._draw_panels(p, mx, my, mw, mh, k, faded=False)
        elif self.taskbar == "cover":
            p.save()
            p.setClipRect(monitor)
            if self.zone is not None:  # panel visible only outside the game's zone
                path_zone = QRectF(mx + self.zone.x * k, my + self.zone.y * k, self.zone.w * k, self.zone.h * k)
                from PySide6.QtGui import QRegion
                p.setClipRegion(QRegion(monitor.toRect()).subtracted(QRegion(path_zone.toRect())))
            self._draw_panels(p, mx, my, mw, mh, k, faded=False)
            p.restore()

        p.setFont(self.font())
        caption = QRectF(0, my + mh + 6, self.width(), 22)
        if self.error:
            p.setPen(QColor(C["error"]))
            p.drawText(caption, Qt.AlignCenter, self.error)
        else:
            p.setPen(QColor(C["muted"]))
            p.drawText(caption, Qt.AlignCenter, self.caption or f"Monitor {sw} × {sh}")
        p.end()


# ---------------------------------------------------------------- editor

POSITIONS = [("left", "Left"), ("center", "Center"), ("right", "Right"), ("custom", "Custom")]


class Editor(QWidget):
    """Form for one preset. Emits ``changed`` on any user edit."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        # -- game
        game = Card("Game")
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. rocketleague")
        self.name_error = _label("", "error", wrap=True)
        game.field("Preset name",
                   "Used in the launch option (gwa run rocketleague). Letters, numbers, - and _ only.",
                   self.name, self.name_error)
        self.command = QLineEdit()
        self.command.setPlaceholderText("optional, e.g. ~/Games/MyGame/start.sh")
        game.field("Game command",
                   "Optional. Only needed if you start the game with gwa run directly, "
                   "not from Steam or Heroic.", self.command)
        lay.addWidget(game)

        # -- zone
        zone = Card("Zone", "Where the game appears on your monitor and how big it is.")
        self.monitor_box = QComboBox()
        self.refresh_btn = QPushButton("Detect again")
        self.refresh_btn.setToolTip("Look for monitors and taskbars again, e.g. after plugging one in.")
        self.screen_w, self.screen_h = _spin(320, 15360), _spin(240, 8640)
        self.manual_screen = QWidget()
        ms = _row("Resolution", self.screen_w, "×", self.screen_h)
        ms.setContentsMargins(0, 4, 0, 0)
        self.manual_screen.setLayout(ms)
        self.monitor_note = _label("", "desc", wrap=True)
        zone.field("Monitor",
                   "Which monitor the game goes on. gwa reads its resolution, position and scale "
                   "each time the game starts. Choose Manual to type a resolution yourself.",
                   _row(self.monitor_box, self.refresh_btn), self.manual_screen, self.monitor_note)

        self.pos_group = QButtonGroup(self)
        self.pos_buttons: dict[str, QPushButton] = {}
        pos_row = QHBoxLayout()
        pos_row.setSpacing(6)
        for key, text in POSITIONS:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setMinimumWidth(84)
            self.pos_group.addButton(b)
            self.pos_buttons[key] = b
            pos_row.addWidget(b)
        pos_row.addStretch(1)
        self.pos_x, self.pos_y = _spin(0, 15360), _spin(0, 8640)
        self.pos_xy = QWidget()
        xy = _row("X", self.pos_x, "Y", self.pos_y)
        xy.setContentsMargins(0, 4, 0, 0)
        self.pos_xy.setLayout(xy)
        zone.field("Position",
                   "Left, center or right edge of the monitor. Custom lets you place the "
                   "top-left corner anywhere.", pos_row, self.pos_xy)

        self.sizes = QListWidget()
        self.sizes.setSelectionMode(QAbstractItemView.SingleSelection)
        self.sizes.setFixedHeight(190)
        self.custom_w, self.custom_h = _spin(64, 15360), _spin(64, 8640)
        self.custom_size = QWidget()
        cs = _row("Width", self.custom_w, "Height", self.custom_h)
        cs.setContentsMargins(0, 4, 0, 0)
        self.custom_size.setLayout(cs)
        zone.field("Game size",
                   "The size of the game window. Pick one from the list, or choose "
                   "“Custom size…” at the bottom for anything else.", self.sizes, self.custom_size)
        lay.addWidget(zone)

        # -- taskbar
        tb = Card("Taskbar", "What happens to your Plasma panel while this game runs.")
        self.taskbar_group = QButtonGroup(self)
        self.taskbar_buttons: dict[str, QRadioButton] = {}
        choices = [
            ("leave", "Leave as is",
             "Nothing changes. An always-visible taskbar may cover the bottom of the game."),
            ("fit", "Fit the game above the taskbar",
             "The zone gets shorter by the taskbar's height, so nothing overlaps and the taskbar "
             "stays visible everywhere."),
            ("autohide", "Auto-hide the taskbar while playing",
             "The taskbar hides across the whole monitor when the game starts and comes back when "
             "it closes. Needs the game started with its launch option."),
            ("cover", "Game covers the taskbar in its zone",
             "Like real fullscreen: the game sits on top of the taskbar, which stays visible next "
             "to it. Needs a recent Plasma 6 (KWin's Layer rule)."),
        ]
        for key, title, desc in choices:
            rb = QRadioButton(title)
            self.taskbar_group.addButton(rb)
            self.taskbar_buttons[key] = rb
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(rb)
            d = _label(desc, "desc", wrap=True)
            d.setContentsMargins(26, 0, 0, 0)
            box.addWidget(d)
            tb.body.addLayout(box)
        self.taskbar_note = _label("", "desc", wrap=True)
        tb.body.addWidget(self.taskbar_note)
        lay.addWidget(tb)

        # -- performance
        perf = Card("Performance")
        self.render_on = QCheckBox("Render at a lower resolution")
        self.render_w, self.render_h = _spin(64, 15360), _spin(64, 8640)
        self.render_row = QWidget()
        rr = _row(self.render_w, "×", self.render_h)
        rr.setContentsMargins(26, 0, 0, 0)
        self.render_row.setLayout(rr)
        perf.field("Upscaling",
                   "The game renders smaller and gamescope scales it up to fill the zone. "
                   "More FPS, slightly softer picture.", self.render_on, self.render_row)
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("e.g. -r 144")
        perf.field("Extra gamescope options",
                   "Passed straight to gamescope. For example -r 144 caps the frame rate at 144.",
                   self.extra)
        lay.addWidget(perf)

        # -- advanced (collapsible)
        self.adv_toggle = QToolButton()
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setText("▸  Advanced settings")
        lay.addWidget(self.adv_toggle)
        self.advanced = Card("Advanced", "Most people can leave these alone.")
        self.origin_x, self.origin_y = _spin(-30000, 30000), _spin(-30000, 30000)
        self.advanced.field("Monitor position in desktop layout",
                            "Only for multiple monitors: where this monitor's top-left corner is "
                            "in System Settings → Display Configuration. Filled in automatically "
                            "when a detected monitor is selected.",
                            _row("X", self.origin_x, "Y", self.origin_y))
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.5, 4.0)
        self.scale.setSingleStep(0.05)
        self.scale.setDecimals(2)
        self.scale.setMinimumWidth(110)
        self.advanced.field("Display scale",
                            "Match your scaling in System Settings → Display Configuration "
                            "(1.25 means 125%). Filled in automatically for a detected monitor.",
                            _row(self.scale))
        self.wmclass = QLineEdit()
        self.advanced.field("Window class",
                            "The window KWin moves. Leave as gamescope unless you know you need "
                            "something else.", self.wmclass)
        self.advanced.setVisible(False)
        lay.addWidget(self.advanced)
        lay.addStretch(1)

        # -- wiring
        for w in (self.name, self.command, self.extra, self.wmclass):
            w.textEdited.connect(self._edited)
        for w in (self.screen_w, self.screen_h):
            w.valueChanged.connect(self._screen_changed)
        for w in (self.pos_x, self.pos_y, self.custom_w, self.custom_h, self.render_w,
                  self.render_h, self.origin_x, self.origin_y, self.scale):
            w.valueChanged.connect(self._edited)
        self.pos_group.buttonToggled.connect(lambda _b, on: on and self._area_changed())
        self.sizes.currentItemChanged.connect(lambda *_: self._edited())
        self.render_on.toggled.connect(self._edited)
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        self.monitor_box.currentIndexChanged.connect(self._monitor_changed)
        self.taskbar_group.buttonToggled.connect(lambda _b, on: on and self._area_changed())

        self.live = Live()
        # screen/origin/scale stored with the preset: kept as a fallback while following a monitor
        self._fallback: tuple[tuple[int, int], tuple[int, int], float] = ((3440, 1440), (0, 0), 1.0)

    # ---- helpers

    def _toggle_advanced(self, on: bool) -> None:
        self.advanced.setVisible(on)
        self.adv_toggle.setText(("▾" if on else "▸") + "  Advanced settings")

    def _screen(self) -> tuple[int, int]:
        return self.screen_w.value(), self.screen_h.value()

    def _monitor_choice(self) -> str:
        return self.monitor_box.currentData() or ""

    def _monitor(self) -> Monitor | None:
        return self.live.find(self._monitor_choice())

    def _taskbar(self) -> str:
        for key, b in self.taskbar_buttons.items():
            if b.isChecked():
                return key
        return "leave"

    def panel_insets(self) -> tuple[int, int, int, int]:
        """Space taken by always-visible panels on the chosen monitor (physical px)."""
        if self.live.panel_error:
            return (0, 0, 0, 0)
        return monitors.insets(self.live.panels_on(self._monitor()), self.scale.value())

    def _insets(self) -> tuple[int, int, int, int]:
        """Insets the zone must respect: only for 'fit' with a non-custom position."""
        if self._taskbar() != "fit" or self._position() == "custom":
            return (0, 0, 0, 0)
        return self.panel_insets()

    def _area(self) -> tuple[int, int]:
        sw, sh = self._screen()
        l, t, r, b = self._insets()
        return sw - l - r, sh - t - b

    def _fill_monitors(self, wanted: str) -> None:
        self.monitor_box.blockSignals(True)
        self.monitor_box.clear()
        if self.live.monitors:
            primary = self.live.find("primary")
            self.monitor_box.addItem(f"Primary monitor  ({primary.label()})", "primary")
            if len(self.live.monitors) > 1:
                for m in self.live.monitors:
                    self.monitor_box.addItem(m.label(), m.name)
        if wanted and wanted != "primary" and self.monitor_box.findData(wanted) < 0:
            self.monitor_box.addItem(f"{wanted}  (not connected)", wanted)
        if wanted == "primary" and self.monitor_box.findData("primary") < 0:
            self.monitor_box.addItem("Primary monitor  (not detected)", "primary")
        self.monitor_box.addItem("Manual", "")
        idx = self.monitor_box.findData(wanted)
        if wanted and self.live.monitors and wanted != "primary" and len(self.live.monitors) == 1 \
                and self.live.find(wanted) is not None:
            idx = self.monitor_box.findData("primary") if idx < 0 else idx
        self.monitor_box.setCurrentIndex(idx if idx >= 0 else self.monitor_box.count() - 1)
        self.monitor_box.blockSignals(False)

    def _apply_monitor_values(self) -> None:
        """Show the followed monitor's live values in the screen/origin/scale fields."""
        m = self._monitor()
        follow = bool(self._monitor_choice())
        if m is not None:
            self.screen_w.setValue(m.width)
            self.screen_h.setValue(m.height)
            self.origin_x.setValue(m.x)
            self.origin_y.setValue(m.y)
            self.scale.setValue(m.scale)
        elif follow:  # followed monitor not connected: show the stored fallback
            (sw, sh), (ox, oy), sc = self._fallback
            self.screen_w.setValue(sw)
            self.screen_h.setValue(sh)
            self.origin_x.setValue(ox)
            self.origin_y.setValue(oy)
            self.scale.setValue(sc)
        self.manual_screen.setVisible(not follow)
        for w in (self.origin_x, self.origin_y, self.scale):
            w.setEnabled(not follow)
        if not follow:
            note = ""
        elif m is None:
            note = (f"Not connected right now: using the stored {self._fallback[0][0]} × "
                    f"{self._fallback[0][1]} until it is.")
        else:
            x, y, _, _ = m.logical
            note = f"Detected: {m.width} × {m.height} at {x}, {y}, scale {m.scale:g}."
        if self.live.monitor_error and not self.live.monitors:
            note = f"Couldn't detect monitors ({self.live.monitor_error}). Using Manual."
        self.monitor_note.setText(note)
        self.monitor_note.setVisible(bool(note))

    def _update_taskbar_note(self) -> None:
        if self.live.panel_error:
            text = f"Couldn't detect the taskbar ({self.live.panel_error})."
        else:
            panels = self.live.panels_on(self._monitor())
            modes = {"none": "always visible", "autohide": "auto-hide", "dodgewindows": "dodge windows"}
            if panels:
                text = "Detected: " + "; ".join(
                    f"{p.location} panel, {p.thickness} px, {modes.get(p.hiding, p.hiding)}" for p in panels)
            else:
                text = "No panels detected on this monitor."
            if self._taskbar() == "fit" and self._position() == "custom":
                text += " “Fit” doesn't apply to a custom position."
        self.taskbar_note.setText(text)

    def set_live(self, live: Live) -> None:
        self.live = live

    def _position(self) -> str:
        for key, b in self.pos_buttons.items():
            if b.isChecked():
                return key
        return "left"

    def _size(self) -> tuple[int, int]:
        item = self.sizes.currentItem()
        data = item.data(Qt.UserRole) if item else None
        return tuple(data) if data else (self.custom_w.value(), self.custom_h.value())

    def _fill_sizes(self, keep: tuple[int, int] | None) -> None:
        """Rebuild the list for the current screen and select ``keep`` (or Custom if not listed)."""
        self.sizes.blockSignals(True)
        self.sizes.clear()
        target = None
        for c in size_choices(self._area()):
            it = QListWidgetItem(f"{c.w} × {c.h}     {c.note}")
            it.setData(Qt.UserRole, (c.w, c.h))
            self.sizes.addItem(it)
            if keep == (c.w, c.h):
                target = it
        custom = QListWidgetItem("Custom size…")
        custom.setData(Qt.UserRole, None)
        f = custom.font()
        f.setItalic(True)
        custom.setFont(f)
        self.sizes.addItem(custom)
        if target is None and keep is not None:
            target = custom
            self.custom_w.setValue(keep[0])
            self.custom_h.setValue(keep[1])
        self.sizes.setCurrentItem(target or self.sizes.item(2))  # default: half width
        self.sizes.scrollToItem(self.sizes.currentItem(), QAbstractItemView.PositionAtCenter)
        self.sizes.blockSignals(False)

    def _sync_widgets(self) -> None:
        """Visibility and ranges that depend on other fields."""
        sw, sh = self._screen()
        aw, ah = self._area()
        self.custom_w.setMaximum(aw)
        self.custom_h.setMaximum(ah)
        item = self.sizes.currentItem()
        self.custom_size.setVisible(bool(item) and item.data(Qt.UserRole) is None)
        custom_pos = self._position() == "custom"
        self.pos_xy.setVisible(custom_pos)
        w, h = self._size()
        self.pos_x.setMaximum(max(0, sw - w))
        self.pos_y.setMaximum(max(0, sh - h))
        self.render_row.setEnabled(self.render_on.isChecked())
        self.render_w.setMaximum(w)
        self.render_h.setMaximum(h)
        self._update_taskbar_note()

    def _monitor_changed(self) -> None:
        if self._loading:
            return
        m = self._monitor()
        if m is not None:  # newly chosen monitor becomes the stored fallback too
            self._fallback = (m.size, (m.x, m.y), m.scale)
        self._loading = True
        self._apply_monitor_values()
        self._loading = False
        self._area_changed()

    def _area_changed(self) -> None:
        """Screen or usable area changed: rebuild the size list, keeping the size if it still fits."""
        if self._loading:
            return
        self._loading = True
        w, h = self._size()
        aw, ah = self._area()
        self._fill_sizes((min(w, aw), min(h, ah)))
        self._loading = False
        self._edited()

    def _screen_changed(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._fill_sizes(self._size())
        self._loading = False
        self._edited()

    def _edited(self, *_):
        if self._loading:
            return
        self._loading = True
        self._sync_widgets()
        self._loading = False
        self.changed.emit()

    # ---- public

    def load(self, name: str, s: Settings) -> None:
        self._loading = True
        try:
            self.name.setText(name)
            self.command.setText(shlex.join(s.command) if s.command else "")
            self._fallback = (s.screen, s.origin, s.scale)
            self.screen_w.setValue(s.screen[0])
            self.screen_h.setValue(s.screen[1])
            self.origin_x.setValue(s.origin[0])
            self.origin_y.setValue(s.origin[1])
            self.scale.setValue(s.scale)
            self._fill_monitors(s.monitor)
            self._apply_monitor_values()
            self.taskbar_buttons.get(s.taskbar, self.taskbar_buttons["leave"]).setChecked(True)
            self.pos_buttons.get(s.zone, self.pos_buttons["left"]).setChecked(True)
            try:
                z = core.plan(s, self.live).zone
            except ValueError:
                z = compute_zone("left", self._area())
            self.pos_x.setMaximum(15360)
            self.pos_y.setMaximum(8640)
            self.pos_x.setValue(z.x)
            self.pos_y.setValue(z.y)
            self._fill_sizes((z.w, z.h))
            self.render_on.setChecked(s.render is not None)
            rw, rh = s.render or (z.w * 3 // 4, z.h * 3 // 4)
            self.render_w.setMaximum(15360)
            self.render_h.setMaximum(8640)
            self.render_w.setValue(rw)
            self.render_h.setValue(rh)
            self.extra.setText(s.gamescope_args)
            self.wmclass.setText(s.wmclass)
            self._sync_widgets()
        finally:
            self._loading = False

    def read(self) -> tuple[str, Settings]:
        """Current form as (name, Settings). Raises ValueError with a user-facing message."""
        name = self.name.text().strip()
        aw, ah = self._area()
        w, h = self._size()
        pos = self._position()
        if pos == "custom":
            geo = dict(zone="custom", rect=Rect(self.pos_x.value(), self.pos_y.value(), w, h))
        else:
            # Keep presets tidy: the defaults (half the usable width, full usable height) aren't stored.
            geo = dict(zone=pos, width=None if w == aw // 2 else w, height=None if h == ah else h)
        monitor = self._monitor_choice()
        if monitor:  # following a monitor: keep the stored fallback values
            screen, origin, scale = self._fallback
        else:
            screen = self._screen()
            origin = (self.origin_x.value(), self.origin_y.value())
            scale = round(self.scale.value(), 2)
        try:
            command = tuple(shlex.split(self.command.text()))
        except ValueError as e:
            raise ValueError(f"Game command: {e}") from None
        s = Settings(
            screen=screen,
            origin=origin,
            scale=scale,
            monitor=monitor,
            taskbar=self._taskbar(),
            render=(self.render_w.value(), self.render_h.value()) if self.render_on.isChecked() else None,
            gamescope_args=self.extra.text().strip(),
            wmclass=self.wmclass.text().strip() or "gamescope",
            command=command,
            **geo,
        )
        core.plan(s, self.live)  # raises ValueError for anything gwa couldn't use
        return name, s

    def show_name_error(self, msg: str) -> None:
        self.name_error.setText(msg)
        self.name_error.setVisible(bool(msg))
        self.name.setProperty("invalid", bool(msg))
        self.name.style().unpolish(self.name)
        self.name.style().polish(self.name)


# ---------------------------------------------------------------- launch options panel

class LaunchCard(Card):
    def __init__(self):
        super().__init__("Launch options",
                         "Paste these into your launcher once. Every launch then moves the game "
                         "into this preset's zone automatically.")
        warn = _label("Replace any old “gamescope -W …” line already in the launcher, and turn off "
                      "Heroic's own Gamescope setting. A leftover fixed size gives black bars and "
                      "caps the in-game resolution.", "desc", wrap=True)
        warn.setStyleSheet(f"color: {C['warn']};")
        self.body.addWidget(warn)
        self.steam = self._line()
        self.heroic_exe = self._line()
        self.heroic_args = self._line()
        self.field("Steam", "Right-click the game → Properties → General → Launch Options.",
                   self._with_copy(self.steam))
        self.field("Heroic", "Game settings → Advanced → Wrapper command → add a wrapper, then "
                   "click + to save it.",
                   self._with_copy(self.heroic_exe, "Wrapper"), self._with_copy(self.heroic_args, "Arguments"))
        self.note = _label("", "desc", wrap=True)
        self.body.addWidget(self.note)

    @staticmethod
    def _line() -> QLineEdit:
        e = QLineEdit()
        e.setReadOnly(True)
        return e

    def _with_copy(self, line: QLineEdit, caption: str = "") -> QHBoxLayout:
        btn = QPushButton("Copy")
        btn.clicked.connect(lambda: self._copy(line, btn))
        lay = QHBoxLayout()
        lay.setSpacing(8)
        if caption:
            cap = _label(caption, "desc")
            cap.setMinimumWidth(70)
            lay.addWidget(cap)
        lay.addWidget(line, 1)
        lay.addWidget(btn)
        return lay

    @staticmethod
    def _copy(line: QLineEdit, btn: QPushButton) -> None:
        QApplication.clipboard().setText(line.text())
        btn.setText("Copied")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1200, lambda: btn.setText("Copy"))

    def show_for(self, name: str, unsaved: bool) -> None:
        steam, exe, args = core.preset_launch_options(name or "<name>")
        self.steam.setText(steam)
        self.heroic_exe.setText(exe)
        self.heroic_args.setText(args)
        self.steam.setCursorPosition(0)
        self.note.setText("Save first: the launch option reads the saved preset." if unsaved else "")
        self.note.setVisible(unsaved)


# ---------------------------------------------------------------- main window

@dataclass
class Entry:
    saved_name: str | None      # name on disk, None if never saved
    name: str
    settings: Settings
    error: str = ""             # current form error, if any


class MainWindow(QMainWindow):
    def __init__(self, presets_path: Path | None = None, rules_path: Path | None = None,
                 live: Live | None = None):
        super().__init__()
        self.presets_path = presets_path or presets.default_path()
        self.rules_path = rules_path or kwinrules.default_path()
        self.live = live if live is not None else monitors.detect()
        self.entries: list[Entry] = []
        self.saved: dict[str, Settings] = {}
        self.deleted: set[str] = set()
        self.load_error = ""
        self._current = -1

        self.setWindowTitle("Game Window Anywhere")
        self.resize(1080, 820)
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(18, 16, 18, 16)
        body.setSpacing(16)
        outer.addLayout(body, 1)

        # sidebar
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 16, 14, 14)
        sl.setSpacing(10)
        title = _label("Game Window\nAnywhere")
        title.setObjectName("appTitle")
        sl.addWidget(title)
        sub = _label("Play games fullscreen in part of your monitor.", wrap=True)
        sub.setObjectName("appSubtitle")
        sl.addWidget(sub)
        sl.addSpacing(8)
        sl.addWidget(_label("Your games", "cardTitle"))
        self.list = QListWidget()
        sl.addWidget(self.list, 1)
        self.btn_new = QPushButton("New")
        self.btn_dup = QPushButton("Duplicate")
        self.btn_del = QPushButton("Delete")
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(self.btn_new, 0, 0)
        grid.addWidget(self.btn_dup, 0, 1)
        grid.addWidget(self.btn_del, 1, 0, 1, 2)
        sl.addLayout(grid)
        body.addWidget(side)

        # right side: pinned preview above the scrollable editor
        right = QVBoxLayout()
        right.setSpacing(12)
        self.preview_bar = QFrame()
        self.preview_bar.setObjectName("previewBar")
        pl = QVBoxLayout(self.preview_bar)
        pl.setContentsMargins(12, 12, 12, 6)
        self.preview = MonitorPreview()
        pl.addWidget(self.preview)
        right.addWidget(self.preview_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("scrollBody")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 8, 0)
        il.setSpacing(16)
        self.empty = _label("No games yet. Click New to create your first preset.", "desc", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setMinimumHeight(200)
        il.addWidget(self.empty)
        self.editor = Editor()
        il.addWidget(self.editor)
        self.launch = LaunchCard()
        self.editor.layout().insertWidget(self.editor.layout().count() - 1, self.launch)
        scroll.setWidget(inner)
        right.addWidget(scroll, 1)
        body.addLayout(right, 1)

        # footer
        footer = QFrame()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 10, 18, 10)
        self.status = _label("", "desc", wrap=True)
        fl.addWidget(self.status, 1)
        self.btn_apply = QPushButton("Apply zone now")
        self.btn_apply.setToolTip(
            "Moves and resizes the game window right away, without launching anything.\n"
            "The game's resolution comes from gamescope, so start the game with this\n"
            "preset's launch option (below) or it may show black bars.")
        self.btn_revert = QPushButton("Revert")
        self.btn_save = _cls(QPushButton("Save"), "primary")
        for b in (self.btn_apply, self.btn_revert, self.btn_save):
            fl.addWidget(b)
        outer.addWidget(footer)

        save_act = QAction(self)
        save_act.setShortcut(QKeySequence.Save)
        save_act.triggered.connect(self.save)
        self.addAction(save_act)

        self.list.currentRowChanged.connect(self._select)
        self.editor.changed.connect(self._form_changed)
        self.btn_new.clicked.connect(self.new_preset)
        self.btn_dup.clicked.connect(self.duplicate_preset)
        self.btn_del.clicked.connect(self.delete_preset)
        self.btn_save.clicked.connect(self.save)
        self.btn_revert.clicked.connect(self.revert)
        self.btn_apply.clicked.connect(self.apply_now)
        self.editor.set_live(self.live)
        self.editor.refresh_btn.clicked.connect(self.redetect)

        self._load_from_disk()
        self._restore_stale_taskbar()

    # ---- state

    def _load_from_disk(self) -> None:
        try:
            self.saved = presets.load(self.presets_path)
            self.load_error = ""
        except ValueError as e:
            self.saved = {}
            self.load_error = str(e)
        self.entries = [Entry(n, n, s) for n, s in sorted(self.saved.items())]
        self.deleted = set()
        self._current = -1
        self._rebuild_list(0 if self.entries else -1)
        if self.load_error:
            self._set_status(f"Couldn't read your presets file, so saving is disabled to protect it. "
                             f"Fix it in a text editor and reopen: {self.load_error}", "error")

    def _entry_dirty(self, e: Entry) -> bool:
        return e.saved_name is None or e.name != e.saved_name or e.settings != self.saved.get(e.saved_name)

    def is_dirty(self) -> bool:
        return bool(self.deleted) or any(self._entry_dirty(e) or e.error for e in self.entries)

    def change_summary(self) -> list[str]:
        out = []
        for e in self.entries:
            if e.saved_name is None:
                out.append(f"{e.name or '(unnamed)'}: new")
            elif e.name != e.saved_name:
                out.append(f"{e.saved_name}: renamed to {e.name}")
            elif self._entry_dirty(e) or e.error:
                out.append(f"{e.name}: changed")
        out += [f"{n}: deleted" for n in sorted(self.deleted)]
        return out

    def _rebuild_list(self, select: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.entries:
            self.list.addItem(QListWidgetItem(self._item_text(e)))
        self.list.blockSignals(False)
        has = bool(self.entries)
        self.editor.setVisible(has)
        self.preview_bar.setVisible(has)
        self.empty.setVisible(not has)
        self.btn_dup.setEnabled(has)
        self.btn_del.setEnabled(has)
        self.btn_apply.setEnabled(has)
        if has:
            self.list.setCurrentRow(max(0, min(select, len(self.entries) - 1)))
        self._refresh_chrome()

    def _item_text(self, e: Entry) -> str:
        mark = "  •" if (self._entry_dirty(e) or e.error) else ""
        return f"{e.name or '(unnamed)'}{mark}"

    def _refresh_chrome(self) -> None:
        dirty = self.is_dirty()
        self.setWindowTitle(("* " if dirty else "") + "Game Window Anywhere")
        self.btn_save.setEnabled(dirty and not self.load_error)
        self.btn_revert.setEnabled(dirty)
        for i, e in enumerate(self.entries):
            if self.list.item(i):
                self.list.item(i).setText(self._item_text(e))
        if 0 <= self._current < len(self.entries):
            e = self.entries[self._current]
            self.launch.show_for(e.name, unsaved=self._entry_dirty(e))

    def _set_status(self, text: str, kind: str = "") -> None:
        colour = {"error": C["error"], "ok": C["ok"], "warn": C["warn"]}.get(kind, C["muted"])
        self.status.setStyleSheet(f"color: {colour};")
        self.status.setText(text)

    # ---- editor <-> entries

    def _select(self, row: int) -> None:
        self._current = row
        if 0 <= row < len(self.entries):
            e = self.entries[row]
            self.editor.load(e.name, e.settings)
            self._form_changed(user=False)

    def _form_changed(self, user: bool = True) -> None:
        if not (0 <= self._current < len(self.entries)):
            return
        e = self.entries[self._current]
        name_err = ""
        try:
            name, s = self.editor.read()
            e.settings = s
            e.name = name
            e.error = ""
        except ValueError as exc:
            e.name = self.editor.name.text().strip()
            e.error = str(exc)
        try:
            presets.validate_name(e.name)
        except ValueError as exc:
            name_err = str(exc).replace("preset name ", "Name ")
        if not name_err and any(o is not e and o.name == e.name for o in self.entries):
            name_err = f"Another game is already called '{e.name}'."
        self.editor.show_name_error(name_err)

        panels = self.editor.panel_insets()
        if e.error:
            self.preview.show_zone(self.editor._screen(), None, e.error, panels, self.editor._taskbar())
            self._set_status(e.error, "error")
        else:
            p = core.plan(e.settings, self.live)
            name = p.monitor.name + " · " if p.monitor else ""
            caption = f"{name}{p.settings.screen[0]} × {p.settings.screen[1]}"
            if any(panels):
                caption += {"leave": " · taskbar may overlap the game",
                            "fit": " · game fits above the taskbar",
                            "autohide": " · taskbar auto-hides while playing",
                            "cover": " · game covers the taskbar in its zone"}[e.settings.taskbar]
            self.preview.show_zone(p.settings.screen, p.zone, "", panels, e.settings.taskbar, caption)
            if user:
                self._set_status("Unsaved changes." if self.is_dirty() else "")
        self._refresh_chrome()

    # ---- actions

    def _unique_name(self, base: str) -> str:
        names = {e.name for e in self.entries}
        if base not in names:
            return base
        i = 2
        while f"{base}-{i}" in names:
            i += 1
        return f"{base}-{i}"

    def new_preset(self) -> None:
        self.entries.append(Entry(None, self._unique_name("new-game"),
                                  Settings(zone="left", monitor="primary" if self.live.monitors else "")))
        self._rebuild_list(len(self.entries) - 1)
        self.editor.name.setFocus()
        self.editor.name.selectAll()
        self._set_status("New game added. Give it a name, pick a zone, then Save.")

    def duplicate_preset(self) -> None:
        if not (0 <= self._current < len(self.entries)):
            return
        src = self.entries[self._current]
        self.entries.append(Entry(None, self._unique_name(f"{src.name}-copy"), src.settings))
        self._rebuild_list(len(self.entries) - 1)

    def delete_preset(self) -> None:
        if not (0 <= self._current < len(self.entries)):
            return
        e = self.entries[self._current]
        if self.confirm(f"Delete “{e.name or '(unnamed)'}”?",
                        "It will be removed from your presets when you click Save.\n"
                        "Launch options that use it will stop working.") != QMessageBox.Yes:
            return
        if e.saved_name is not None:
            self.deleted.add(e.saved_name)
        del self.entries[self._current]
        self._rebuild_list(self._current)
        self._set_status("Deleted. Click Save to make it permanent.")

    def save(self) -> bool:
        if self.load_error:
            self._set_status("Saving is disabled because the presets file couldn't be read.", "error")
            return False
        names: set[str] = set()
        for i, e in enumerate(self.entries):
            problem = e.error
            if not problem:
                try:
                    presets.validate_name(e.name)
                except ValueError as exc:
                    problem = str(exc)
            if not problem and e.name in names:
                problem = f"two games are called '{e.name}'"
            if problem:
                self.list.setCurrentRow(i)
                self._set_status(f"Can't save “{e.name or '(unnamed)'}”: {problem}", "error")
                return False
            names.add(e.name)
        try:
            presets.save({e.name: e.settings for e in self.entries}, self.presets_path)
        except OSError as exc:
            self._set_status(f"Couldn't write {self.presets_path}: {exc}", "error")
            return False
        self.saved = {e.name: e.settings for e in self.entries}
        for e in self.entries:
            e.saved_name = e.name
        self.deleted = set()
        self._refresh_chrome()
        self._set_status(f"Saved to {self.presets_path}", "ok")
        return True

    def revert(self) -> None:
        if self.confirm("Discard all unsaved changes?",
                        "\n".join(self.change_summary())) == QMessageBox.Yes:
            self._load_from_disk()
            self._set_status("Changes discarded.")

    def apply_now(self) -> None:
        if not (0 <= self._current < len(self.entries)):
            return
        e = self.entries[self._current]
        if e.error:
            self._set_status(f"Fix this first: {e.error}", "error")
            return
        p = core.plan(e.settings, self.live)
        try:
            _, conflicts = core.write_rule(p.settings, e.name, p.kwin_rect, self.rules_path)
        except OSError as exc:
            self._set_status(f"Couldn't write the KWin rule: {exc}", "error")
            return
        ok, info = kwinrules.reconfigure_kwin()
        msg = f"Window zone set: {p.zone.w} × {p.zone.h} at {p.zone.x}, {p.zone.y}."
        hint = " Start the game with its launch option below so the resolution matches."
        if conflicts:
            self._set_status(msg + f" Another KWin rule may conflict: {conflicts[0]}", "warn")
        elif not ok:
            self._set_status(msg + f" But KWin didn't reload ({info}).", "warn")
        else:
            self._set_status(msg + hint, "ok")

    def redetect(self) -> None:
        """Look for monitors and panels again and refresh the current game's view."""
        self.live = monitors.detect()
        self.editor.set_live(self.live)
        if 0 <= self._current < len(self.entries):
            e = self.entries[self._current]
            self.editor.load(e.name, e.settings)
            self._form_changed(user=False)
        found = ", ".join(m.name for m in self.live.monitors) or "no monitors"
        self._set_status(f"Detected {found}; {len(self.live.panels)} panel(s).")

    def _restore_stale_taskbar(self) -> None:
        """If a game launched with auto-hide was killed, its taskbar change gets undone here."""
        if not taskbar.state_path().exists():
            return
        try:
            restored = taskbar.restore()
        except (OSError, RuntimeError) as exc:
            self._set_status(f"Couldn't restore the taskbar after an earlier game: {exc}", "warn")
            return
        if restored:
            self._set_status("Restored the taskbar, which an earlier game left auto-hidden.", "ok")

    # ---- dialogs (separate methods so tests can stub them)

    def confirm(self, title: str, text: str) -> QMessageBox.StandardButton:
        return QMessageBox.question(self, "Game Window Anywhere", f"{title}\n\n{text}".strip(),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

    def ask_unsaved(self) -> QMessageBox.StandardButton:
        return self.unsaved_dialog().exec()

    def unsaved_dialog(self) -> QMessageBox:
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setIcon(QMessageBox.Warning)
        box.setText("Save your changes before closing?")
        box.setInformativeText("\n".join(self.change_summary()))
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        _cls(box.button(QMessageBox.Save), "primary")
        return box

    def closeEvent(self, event) -> None:
        if not self.is_dirty():
            event.accept()
            return
        choice = self.ask_unsaved()
        if choice == QMessageBox.Save and self.save():
            event.accept()
        elif choice == QMessageBox.Discard:
            event.accept()
        else:
            event.ignore()


def _desktop_entry_installed() -> bool:
    import os
    dirs = [desktop.data_home(), *(os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")]
    return any(Path(d, "applications", f"{DESKTOP_ID}.desktop").is_file() for d in dirs if d)


def main(presets_path: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Game Window Anywhere")
    app.setApplicationVersion(__version__)
    if _desktop_entry_installed():
        # Lets Plasma show the right icon; claiming the ID without a .desktop file makes the
        # portal log "App info not found", so only do it once the entry exists.
        app.setDesktopFileName(DESKTOP_ID)
    app.setWindowIcon(QIcon(str(desktop.ICON_SOURCE)))
    app.setStyle("Fusion")  # consistent base for the blue theme on any Plasma style
    app.setStyleSheet(STYLE)
    win = MainWindow(presets_path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
