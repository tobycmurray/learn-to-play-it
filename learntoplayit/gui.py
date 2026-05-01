from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QKeySequence, QShortcut, QPainter, QColor, QPen, QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QSlider,
    QSizePolicy,
)


from .player import (
    SPEED_STEP, PITCH_STEP, SEEK_SECONDS, NUDGE_SECONDS,
    SPEED_MIN, SPEED_MAX, PITCH_MIN, PITCH_MAX,
)
from .fmt import fmt_time, fmt_pitch

WAVEFORM_BINS = 100
WAVEFORM_COLOR = QColor(70, 130, 220)
PLAYHEAD_COLOR = QColor(255, 60, 60)
LOOP_MARKER_COLOR = QColor(255, 200, 40)
LOOP_FILL_COLOR = QColor(255, 200, 40, 30)
LOOP_SERIF = 6
WAVEFORM_BG = QColor(30, 30, 35)
WAVEFORM_PAD = 4
MONO_FONT = "'Menlo', 'Courier New', monospace"

WINDOW_MIN_W = 900
WINDOW_W = 900
WINDOW_H = 600

TRANSPORT_W = 200
BUTTON_H = 44
SEEK_W = 140
LOOP_W = 170
SLIDER_W = 64

ICON_SIZE = 18

_icon_cache: dict[str, QPixmap] = {}
_ICONS_DIR = Path(__file__).parent / "resources" / "icons"


def _load_icon_pixmap(name: str, color: str) -> QPixmap:
    key = f"{name}:{color}"
    if key in _icon_cache:
        return _icon_cache[key]
    svg_bytes = (_ICONS_DIR / f"{name}.svg").read_bytes()
    svg_str = svg_bytes.decode().replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(svg_str.encode())
    pixmap = QPixmap(QSize(ICON_SIZE, ICON_SIZE))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    _icon_cache[key] = pixmap
    return pixmap


BUTTON_STYLE = """
ActionButton {
    border: 1px solid palette(mid);
    border-radius: 8px;
    font-size: 15px;
}
ActionButton:hover {
    background: palette(midlight);
}
ActionButton:pressed {
    background: palette(dark);
}
"""


class ActionButton(QPushButton):

    def __init__(self, action, key, parent=None, minWidth=200, icon_name=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setFixedSize(minWidth, BUTTON_H)
        btn_layout = QHBoxLayout(self)
        btn_layout.setContentsMargins(12, 0, 12, 0)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(ICON_SIZE, ICON_SIZE)
        if not icon_name:
            self._icon_label.hide()
        btn_layout.addWidget(self._icon_label)

        self._action_label = QLabel(action)
        self._action_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        btn_layout.addWidget(self._action_label)
        btn_layout.addStretch()
        self._key_label = QLabel(key)
        self._key_label.setStyleSheet("color: #8b8f98; font-size: 13px;")
        self._key_label.setFixedWidth(44)
        self._key_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        btn_layout.addWidget(self._key_label)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(BUTTON_STYLE)

    def showEvent(self, event):
        super().showEvent(event)
        if self._icon_name:
            self._update_icon()

    def _update_icon(self):
        color = self.palette().buttonText().color().name()
        self._icon_label.setPixmap(_load_icon_pixmap(self._icon_name, color))
        self._icon_label.show()

    def set_action(self, text, icon_name=None):
        self._action_label.setText(text)
        if icon_name is not None and icon_name != self._icon_name:
            self._icon_name = icon_name
            self._update_icon()


class WaveformWidget(QWidget):

    def __init__(self):
        super().__init__()
        self.player = None
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        pad = WAVEFORM_PAD
        inner_h = h - 2 * pad
        mid = h // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        painter.fillRect(0, 0, w, h, WAVEFORM_BG)

        if self.player is None or w < 10:
            painter.end()
            return

        wd = self.player.waveform_bins(WAVEFORM_BINS)
        bar_w = w / WAVEFORM_BINS

        painter.setPen(Qt.NoPen)
        painter.setBrush(WAVEFORM_COLOR)
        for i, v in enumerate(wd.bins):
            half_h = int(v * inner_h / 2)
            if half_h > 0:
                x = int(i * bar_w)
                bw = int((i + 1) * bar_w) - x
                painter.drawRect(x, mid - half_h, bw, half_h * 2)

        def col_to_x(col):
            return int((col + 0.5) * bar_w)

        ls_x = col_to_x(wd.loop_start_col) if wd.loop_start_col is not None else None
        le_x = col_to_x(wd.loop_end_col) if wd.loop_end_col is not None else None

        if wd.loop_active:
            fill_l = ls_x if ls_x is not None else 0
            fill_r = le_x if le_x is not None else w
            painter.fillRect(fill_l, 0, fill_r - fill_l, h, LOOP_FILL_COLOR)

        pen = QPen(LOOP_MARKER_COLOR, 2)
        painter.setPen(pen)
        top = pad
        bot = h - pad
        if ls_x is not None:
            painter.drawLine(ls_x, top, ls_x, bot)
            painter.drawLine(ls_x, top, ls_x + LOOP_SERIF, top)
            painter.drawLine(ls_x, bot, ls_x + LOOP_SERIF, bot)
        if le_x is not None:
            painter.drawLine(le_x, top, le_x, bot)
            painter.drawLine(le_x, top, le_x - LOOP_SERIF, top)
            painter.drawLine(le_x, bot, le_x - LOOP_SERIF, bot)

        pen = QPen(PLAYHEAD_COLOR, 2)
        painter.setPen(pen)
        x = col_to_x(wd.cursor_col)
        painter.drawLine(x, 0, x, h)

        painter.end()


class SliderControl(QWidget):

    def __init__(self, label, min_val, max_val, step, key_down, key_up, format_fn):
        super().__init__()
        self._format_fn = format_fn
        self.setFixedWidth(SLIDER_W)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignHCenter)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: bold;")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)

        self._value_label = QLabel("")
        self._value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._value_label)

        up_label = QLabel(f"{key_up}")
        up_label.setStyleSheet("color: gray;")
        up_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(up_label)

        self._slider = QSlider(Qt.Vertical)
        self._slider.setRange(min_val, max_val)
        self._slider.setSingleStep(step)
        self._slider.setPageStep(step)
        self._slider.setMinimumHeight(80)
        layout.addWidget(self._slider, alignment=Qt.AlignHCenter)

        down_label = QLabel(f"{key_down}")
        down_label.setStyleSheet("color: gray;")
        down_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(down_label)

    def set_value(self, value):
        self._slider.blockSignals(True)
        self._slider.setValue(value)
        self._slider.blockSignals(False)
        self._value_label.setText(self._format_fn(value))

    @property
    def slider(self):
        return self._slider


class PlayerWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self._build_status(layout)
        self._build_transport(layout)
        self._build_seek(layout)
        self._build_center(layout)
        self._build_loop(layout)
        self._build_mode(layout)

        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(50)

    def _cmd(self, fn):
        if self.player is not None:
            fn(self.player)

    def set_player(self, player):
        self.player = player
        self.waveform.player = player
        self.part_label.setText(f"part: {player.part}")

    def _build_status(self, layout):
        self.status_label = QLabel("⏸  0:00.00 / 0:00.00")
        self.status_label.setStyleSheet(f"font-size: 22px; font-family: {MONO_FONT}; font-weight: bold;")
        layout.addWidget(self.status_label)

    def _build_transport(self, layout):
        row = QHBoxLayout()

        row.addStretch()

        self.play_btn = ActionButton("Play", "Space", minWidth=TRANSPORT_W, icon_name="play")
        self.play_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_play()))
        row.addWidget(self.play_btn)
        row.addSpacing(28)

        restart_btn = ActionButton("Restart", "0", minWidth=TRANSPORT_W, icon_name="skip-back")
        restart_btn.clicked.connect(lambda: self._cmd(lambda p: p.restart()))
        row.addWidget(restart_btn)
        row.addSpacing(28)

        self.hold_btn = ActionButton("Hold", "H", minWidth=TRANSPORT_W, icon_name="rotate-ccw")
        self.hold_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_hold()))
        row.addWidget(self.hold_btn)

        row.addStretch()
        layout.addLayout(row)

    def _build_seek(self, layout):
        row = QHBoxLayout()
        row.addStretch()

        seek = f"{SEEK_SECONDS:g}s"
        nudge = f"{NUDGE_SECONDS:g}s"
        for idx, (action, key, seconds, icon) in enumerate([
            (seek, "Z", -SEEK_SECONDS, "rewind"),
            (nudge, "X", -NUDGE_SECONDS, "step-back"),
            (nudge, "C", NUDGE_SECONDS, "step-forward"),
            (seek, "V", SEEK_SECONDS, "fast-forward"),
        ]):
            if idx:
                row.addSpacing(20)
            btn = ActionButton(action, key, minWidth=SEEK_W, icon_name=icon)
            btn.clicked.connect(lambda _, s=seconds: self._cmd(lambda p: p.seek(s)))
            row.addWidget(btn)

        row.addStretch()
        layout.addLayout(row)

    def _build_center(self, layout):
        row = QHBoxLayout()

        self.waveform = WaveformWidget()
        row.addWidget(self.waveform, stretch=1)
        row.addSpacing(18)

        self.speed_slider = SliderControl(
            "Speed", int(SPEED_MIN * 100), int(SPEED_MAX * 100),
            int(SPEED_STEP * 100), "S", "W", lambda v: f"{v}%",
        )
        self.speed_slider.slider.valueChanged.connect(
            lambda v: self._cmd(lambda p: p.change_speed(v / 100 - p.speed))
        )
        row.addWidget(self.speed_slider)
        row.addSpacing(12)

        self.pitch_slider = SliderControl(
            "Pitch", PITCH_MIN, PITCH_MAX,
            PITCH_STEP, "D", "E", fmt_pitch,
        )
        self.pitch_slider.slider.valueChanged.connect(
            lambda v: self._cmd(lambda p: p.change_pitch(v - p.cents))
        )
        row.addWidget(self.pitch_slider)

        layout.addLayout(row, stretch=1)

    def _build_loop(self, layout):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        row = QHBoxLayout()

        start_btn = ActionButton("Set Loop Start", "[", minWidth=LOOP_W)
        start_btn.clicked.connect(lambda: self._cmd(lambda p: p.set_loop_start()))
        row.addWidget(start_btn)

        end_btn = ActionButton("Set Loop End", "]", minWidth=LOOP_W)
        end_btn.clicked.connect(lambda: self._cmd(lambda p: p.set_loop_end()))
        row.addWidget(end_btn)

        self.loop_btn = ActionButton("Enable Loop", "L", minWidth=LOOP_W, icon_name="repeat")
        self.loop_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_loop()))
        row.addWidget(self.loop_btn)
        row.addSpacing(16)

        self.loop_status = QLabel("")
        self.loop_status.setMinimumWidth(90)
        row.addWidget(self.loop_status)

        self.loop_label = QLabel("")
        self.loop_label.setStyleSheet(f"font-family: {MONO_FONT};")
        self.loop_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self.loop_label, 1)

        layout.addLayout(row)

    def _build_mode(self, layout):
        row = QHBoxLayout()

        self.mode_btn = ActionButton("Change Mode", "M", minWidth=LOOP_W)
        self.mode_btn.clicked.connect(lambda: self._cmd(lambda p: p.change_mode()))
        row.addWidget(self.mode_btn)
        row.addSpacing(16)

        self.mode_label = QLabel("")
        row.addWidget(self.mode_label)
        row.addSpacing(12)

        self.part_label = QLabel("")
        self.part_label.setStyleSheet("color: gray;")
        row.addWidget(self.part_label)

        row.addStretch()
        layout.addLayout(row)

    def _refresh(self):
        p = self.player
        if p is None:
            return

        if p.hold is not None:
            state = "⏺"
        elif p.playing:
            state = "▶"
        else:
            state = "⏸"
        self.status_label.setText(f"{state}  {fmt_time(p.playback_position)} / {fmt_time(p.song_duration)}")

        self.speed_slider.set_value(int(round(p.speed * 100)))
        self.pitch_slider.set_value(int(round(p.cents)))

        self.play_btn.set_action("Pause" if p.playing else "Play", icon_name="pause" if p.playing else "play")
        self.hold_btn.set_action("Release" if p.hold is not None else "Hold")
        self.mode_label.setText(f"<b>Playback Mode:</b> {p.mode}")

        loop = p.loop
        can_toggle = loop is not None and loop.is_complete()
        self.loop_btn.setEnabled(can_toggle)

        bounds = p.loop_bounds
        if bounds is not None and (bounds[0] is not None or bounds[1] is not None):
            ls = fmt_time(bounds[0]) if bounds[0] is not None else "?"
            le = fmt_time(bounds[1]) if bounds[1] is not None else "?"
            active = bounds[2]
            self.loop_status.setText(f"<b>Loop:</b> {'on' if active else 'off'}")
            self.loop_label.setText(f"{ls} – {le}")
            self.loop_btn.set_action("Disable Loop" if active else "Enable Loop",
                                     icon_name="repeat-off" if active else "repeat")
        else:
            self.loop_status.setText("<b>Loop:</b> off")
            self.loop_label.setText("")
            self.loop_btn.set_action("Enable Loop", icon_name="repeat")

        self.waveform.update()


class GuiDisplay(QMainWindow):
    """Standalone window for --gui CLI mode."""

    def __init__(self, player):
        self.app = QApplication.instance() or QApplication([])
        super().__init__()
        self.player = player

        self.setWindowTitle(f"ltpi — {player.part}")
        self.setMinimumWidth(WINDOW_MIN_W)
        self.resize(WINDOW_W, WINDOW_H)

        self.player_widget = PlayerWidget()
        self.setCentralWidget(self.player_widget)
        self.player_widget.set_player(player)

        self._bind_keys()

    def _bind_keys(self):
        shortcuts = {
            Qt.Key_Space: lambda: self.player.toggle_play(),
            Qt.Key_Q: self.close,
            Qt.Key_0: lambda: self.player.restart(),
            Qt.Key_W: lambda: self.player.change_speed(SPEED_STEP),
            Qt.Key_S: lambda: self.player.change_speed(-SPEED_STEP),
            Qt.Key_E: lambda: self.player.change_pitch(PITCH_STEP),
            Qt.Key_D: lambda: self.player.change_pitch(-PITCH_STEP),
            Qt.Key_Z: lambda: self.player.seek(-SEEK_SECONDS),
            Qt.Key_X: lambda: self.player.seek(-NUDGE_SECONDS),
            Qt.Key_C: lambda: self.player.seek(NUDGE_SECONDS),
            Qt.Key_V: lambda: self.player.seek(SEEK_SECONDS),
            Qt.Key_M: lambda: self.player.change_mode(),
            Qt.Key_H: lambda: self.player.toggle_hold(),
            Qt.Key_L: lambda: self.player.toggle_loop(),
            Qt.Key_BracketLeft: lambda: self.player.set_loop_start(),
            Qt.Key_BracketRight: lambda: self.player.set_loop_end(),
        }
        for key, fn in shortcuts.items():
            QShortcut(QKeySequence(key), self).activated.connect(fn)

    def closeEvent(self, event):
        self.player.quit = True
        event.accept()

    def run(self):
        self.player.start()
        self.show()
        try:
            self.app.exec()
        finally:
            self.player_widget._timer.stop()
            self.player.stop()
