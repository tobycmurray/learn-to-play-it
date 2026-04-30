from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QSlider,
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
WAVEFORM_BG = QColor(30, 30, 35)
MONO_FONT = "'Menlo', 'Courier New', monospace"


class WaveformWidget(QWidget):

    def __init__(self):
        super().__init__()
        self.player = None
        self.setMinimumHeight(120)

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
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
            bar_h = int(v * h)
            if bar_h > 0:
                x = int(i * bar_w)
                bw = int((i + 1) * bar_w) - x
                painter.drawRect(x, h - bar_h, bw, bar_h)

        def col_to_x(col):
            return int((col + 0.5) * bar_w)

        pen = QPen(LOOP_MARKER_COLOR, 2)
        painter.setPen(pen)
        if wd.loop_start_col is not None:
            x = col_to_x(wd.loop_start_col)
            painter.drawLine(x, 0, x, h)
        if wd.loop_end_col is not None:
            x = col_to_x(wd.loop_end_col)
            painter.drawLine(x, 0, x, h)

        pen = QPen(PLAYHEAD_COLOR, 2)
        painter.setPen(pen)
        x = col_to_x(wd.cursor_col)
        painter.drawLine(x, 0, x, h)

        painter.end()


class SliderControl(QWidget):

    def __init__(self, label, min_val, max_val, step, key_down, key_up, format_fn):
        super().__init__()
        self._format_fn = format_fn

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignHCenter)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)

        self._value_label = QLabel("")
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._value_label)

        up_label = QLabel(f"[{key_up}]")
        up_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(up_label)

        self._slider = QSlider(Qt.Vertical)
        self._slider.setRange(min_val, max_val)
        self._slider.setSingleStep(step)
        self._slider.setPageStep(step)
        self._slider.setMinimumHeight(80)
        layout.addWidget(self._slider, alignment=Qt.AlignHCenter)

        down_label = QLabel(f"[{key_down}]")
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

        self.play_btn = QPushButton("▶  Play  [Space]")
        self.play_btn.setFixedHeight(40)
        self.play_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_play()))
        row.addWidget(self.play_btn)

        restart_btn = QPushButton("⏮  Restart  [0]")
        restart_btn.setFixedHeight(40)
        restart_btn.clicked.connect(lambda: self._cmd(lambda p: p.restart()))
        row.addWidget(restart_btn)

        self.hold_btn = QPushButton("⏺  Hold  [H]")
        self.hold_btn.setFixedHeight(40)
        self.hold_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_hold()))
        row.addWidget(self.hold_btn)

        layout.addLayout(row)

    def _build_seek(self, layout):
        row = QHBoxLayout()

        for label, seconds in [
            ("«  −5s  [Z]", -SEEK_SECONDS),
            ("‹  −0.05s  [X]", -NUDGE_SECONDS),
            ("›  +0.05s  [C]", NUDGE_SECONDS),
            ("»  +5s  [V]", SEEK_SECONDS),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda _, s=seconds: self._cmd(lambda p: p.seek(s)))
            row.addWidget(btn)

        layout.addLayout(row)

    def _build_center(self, layout):
        row = QHBoxLayout()

        self.waveform = WaveformWidget()
        row.addWidget(self.waveform, stretch=1)

        self.speed_slider = SliderControl(
            "Speed", int(SPEED_MIN * 100), int(SPEED_MAX * 100),
            int(SPEED_STEP * 100), "S", "W", lambda v: f"{v}%",
        )
        self.speed_slider.slider.valueChanged.connect(
            lambda v: self._cmd(lambda p: p.change_speed(v / 100 - p.speed))
        )
        row.addWidget(self.speed_slider)

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
        row.addWidget(QLabel("Loop"))

        start_btn = QPushButton("[  Start")
        start_btn.clicked.connect(lambda: self._cmd(lambda p: p.set_loop_start()))
        row.addWidget(start_btn)

        end_btn = QPushButton("]  End")
        end_btn.clicked.connect(lambda: self._cmd(lambda p: p.set_loop_end()))
        row.addWidget(end_btn)

        self.loop_btn = QPushButton("OFF  [L]")
        self.loop_btn.setFixedWidth(80)
        self.loop_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_loop()))
        row.addWidget(self.loop_btn)

        self.loop_label = QLabel("")
        self.loop_label.setStyleSheet(f"font-family: {MONO_FONT};")
        row.addWidget(self.loop_label)

        row.addStretch()
        layout.addLayout(row)

    def _build_mode(self, layout):
        row = QHBoxLayout()
        row.addWidget(QLabel("Mode"))

        self.mode_btn = QPushButton("solo  [M]")
        self.mode_btn.setFixedWidth(100)
        self.mode_btn.clicked.connect(lambda: self._cmd(lambda p: p.change_mode()))
        row.addWidget(self.mode_btn)

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

        self.play_btn.setText("⏸  Pause  [Space]" if p.playing else "▶  Play  [Space]")
        self.hold_btn.setText("⏺  Release  [H]" if p.hold is not None else "⏺  Hold  [H]")
        self.mode_btn.setText(f"{p.mode}  [M]")

        bounds = p.loop_bounds
        if bounds is not None and (bounds[0] is not None or bounds[1] is not None):
            ls = fmt_time(bounds[0]) if bounds[0] is not None else "?"
            le = fmt_time(bounds[1]) if bounds[1] is not None else "?"
            self.loop_label.setText(f"{ls} – {le}")
            self.loop_btn.setText("ON  [L]" if bounds[2] else "OFF  [L]")
        else:
            self.loop_label.setText("")
            self.loop_btn.setText("OFF  [L]")

        self.waveform.update()


class GuiDisplay(QMainWindow):
    """Standalone window for --gui CLI mode."""

    def __init__(self, player):
        self.app = QApplication.instance() or QApplication([])
        super().__init__()
        self.player = player

        self.setWindowTitle(f"ltpi — {player.part}")
        self.setMinimumWidth(480)

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
