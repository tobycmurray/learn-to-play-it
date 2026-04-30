import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame,
)

from .player import (
    SPEED_STEP, PITCH_STEP, SEEK_SECONDS, NUDGE_SECONDS,
)
from .fmt import fmt_time, fmt_pitch

WAVEFORM_BINS = 100
WAVEFORM_COLOR = QColor(70, 130, 220)
PLAYHEAD_COLOR = QColor(255, 60, 60)
LOOP_MARKER_COLOR = QColor(255, 200, 40)
WAVEFORM_BG = QColor(30, 30, 35)
MONO_FONT = "'Menlo', 'Courier New', monospace"


class WaveformWidget(QWidget):

    def __init__(self, player):
        super().__init__()
        self.player = player
        self.setMinimumHeight(120)

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        painter.fillRect(0, 0, w, h, WAVEFORM_BG)

        if w < 10:
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


class GuiDisplay(QMainWindow):

    def __init__(self, player):
        self.app = QApplication.instance() or QApplication(sys.argv)
        super().__init__()
        self.player = player

        self.setWindowTitle(f"ltpi — {player.part}")
        self.setMinimumWidth(480)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self._build_status(layout)
        self._build_transport(layout)
        self._build_waveform(layout)
        self.speed_label = self._build_adjuster(layout, "Speed", SPEED_STEP, player.change_speed, "S", "W", width=60)
        self.pitch_label = self._build_adjuster(layout, "Pitch", PITCH_STEP, player.change_pitch, "D", "E", width=90)
        self._build_loop(layout)
        self._build_mode(layout)

        self._bind_keys()

        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)

    # --- UI construction ---

    def _build_status(self, layout):
        self.status_label = QLabel("⏸  0:00.00 / 0:00.00")
        self.status_label.setStyleSheet(f"font-size: 22px; font-family: {MONO_FONT}; font-weight: bold;")
        layout.addWidget(self.status_label)

    def _build_transport(self, layout):
        row = QHBoxLayout()

        self.play_btn = QPushButton("▶  Play  [Space]")
        self.play_btn.setFixedHeight(40)
        self.play_btn.clicked.connect(lambda: self.player.toggle_play())
        row.addWidget(self.play_btn)

        restart_btn = QPushButton("⏮  Restart  [0]")
        restart_btn.setFixedHeight(40)
        restart_btn.clicked.connect(lambda: self.player.restart())
        row.addWidget(restart_btn)

        self.hold_btn = QPushButton("⏺  Hold  [H]")
        self.hold_btn.setFixedHeight(40)
        self.hold_btn.clicked.connect(lambda: self.player.toggle_hold())
        row.addWidget(self.hold_btn)

        layout.addLayout(row)

    def _build_waveform(self, layout):
        self.waveform = WaveformWidget(self.player)
        layout.addWidget(self.waveform)

    @staticmethod
    def _build_adjuster(layout, label, step, command, key_down, key_up, width=60):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))

        minus = QPushButton(f"−  [{key_down}]")
        minus.setFixedWidth(64)
        minus.clicked.connect(lambda: command(-step))
        row.addWidget(minus)

        value_label = QLabel("")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setFixedWidth(width)
        value_label.setStyleSheet("font-weight: bold;")
        row.addWidget(value_label)

        plus = QPushButton(f"+  [{key_up}]")
        plus.setFixedWidth(64)
        plus.clicked.connect(lambda: command(step))
        row.addWidget(plus)

        row.addStretch()
        layout.addLayout(row)
        return value_label

    def _build_loop(self, layout):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        row = QHBoxLayout()
        row.addWidget(QLabel("Loop"))

        start_btn = QPushButton("[  Start")
        start_btn.clicked.connect(lambda: self.player.set_loop_start())
        row.addWidget(start_btn)

        end_btn = QPushButton("]  End")
        end_btn.clicked.connect(lambda: self.player.set_loop_end())
        row.addWidget(end_btn)

        self.loop_btn = QPushButton("OFF  [L]")
        self.loop_btn.setFixedWidth(80)
        self.loop_btn.clicked.connect(lambda: self.player.toggle_loop())
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
        self.mode_btn.clicked.connect(lambda: self.player.change_mode())
        row.addWidget(self.mode_btn)

        self.part_label = QLabel(f"part: {self.player.part}")
        self.part_label.setStyleSheet("color: gray;")
        row.addWidget(self.part_label)

        row.addStretch()
        layout.addLayout(row)

    # --- Keyboard shortcuts ---

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

    # --- Refresh ---

    def _refresh(self):
        p = self.player

        if p.hold is not None:
            state = "⏺"
        elif p.playing:
            state = "▶"
        else:
            state = "⏸"
        self.status_label.setText(f"{state}  {fmt_time(p.playback_position)} / {fmt_time(p.song_duration)}")

        self.speed_label.setText(f"{int(round(p.speed * 100))}%")
        self.pitch_label.setText(fmt_pitch(p.cents))

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

    # --- Lifecycle ---

    def closeEvent(self, event):
        self.player.quit = True
        event.accept()

    def run(self):
        self.player.start()
        self.show()
        self._timer.start(50)
        try:
            self.app.exec()
        finally:
            self._timer.stop()
            self.player.stop()
