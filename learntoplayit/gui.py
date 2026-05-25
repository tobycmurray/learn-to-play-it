from pathlib import Path

import numpy as np
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

DEFAULT_VIEWPORT_SECONDS = 10.0
ZOOM_WHEEL_FACTOR_PER_NOTCH = 1.15
WAVEFORM_COLOR = QColor(70, 130, 220)
PLAYHEAD_COLOR = QColor(255, 60, 60)
BEAT_RULER_COLOR = QColor(230, 230, 220, 70)
BEAT_TICK_COLOR = QColor(230, 230, 220, 135)
DOWNBEAT_TICK_COLOR = QColor(245, 245, 230, 210)
LOOP_MARKER_COLOR = QColor(255, 200, 40)
LOOP_FILL_COLOR = QColor(255, 200, 40, 30)
LOOP_SERIF = 6
SNAP_MODIFIER = Qt.ShiftModifier
WAVEFORM_BG = QColor(30, 30, 35)
HOVER_COLOR = QColor(180, 180, 180, 140)
WAVEFORM_PAD_TOP = 6
WAVEFORM_PAD_BOTTOM = 18
BEAT_TICK_H = 6
DOWNBEAT_TICK_H = 12
MONO_FONT = "'Menlo', 'Courier New'"

WINDOW_MIN_W = 1100
WINDOW_W = 1100
WINDOW_H = 600

TRANSPORT_W = 200
BUTTON_H = 44
SEEK_W = 140
LOOP_W = 190
SLIDER_W = 64

ICON_SIZE = 18

_icon_cache: dict[str, QPixmap] = {}
_ICONS_DIR = Path(__file__).parent / "resources" / "icons"


def _load_icon_pixmap(name: str, color: str) -> QPixmap:
    key = f"{name}:{color}"
    if key in _icon_cache:
        return _icon_cache[key]
    svg_bytes = (_ICONS_DIR / f"{name}.svg").read_bytes()
    svg_str = svg_bytes.decode().replace('stroke="currentColor"', f'stroke="{color}"').replace('fill="currentColor"', f'fill="{color}"')
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


def _peak_per_pixel(bins: np.ndarray, w: int, bin_offset: float) -> np.ndarray:
    """Per-pixel peak envelope for waveform rendering.

    `bins` has length num_bins + 1; the +1 is the partial bin past the
    viewport's right edge. Returns an array of length `w` with the peak
    amplitude per pixel column.

    Each pixel column x covers bin indices [x*bpp + bin_offset,
    (x+1)*bpp + bin_offset). reduceat takes the max over [starts[i],
    starts[i+1]) for i<w-1 and [starts[w-1], len(bins)) for the last —
    so the rightmost pixel naturally includes the +1 partial-edge bin.
    Removing the +1, or changing the bin_offset sign, would silently
    break the right-edge / smooth-scroll behavior; tests pin this.
    """
    num_bins = len(bins) - 1
    bins_per_pixel = num_bins / w
    starts = (np.arange(w) * bins_per_pixel + bin_offset).astype(int)
    return np.maximum.reduceat(bins, starts)


class ViewportZoom:
    """Waveform viewport zoom level.

    Stored as a float (seconds) but exposed only as an integer bin count.

    Why: Player.waveform_bins() requires an integer num_bins — it sizes a
    numpy array. But zoom intent must accumulate as a float; if we stored
    bins as an int and multiplied per wheel tick, small ticks at high zoom
    would round back to the same int and get lost ("stuck wheel"). Keeping
    seconds as the source of truth, rounding only when handing off to
    waveform_bins(), preserves intent across sub-bin wheel ticks.

    Invariant: callers must obtain bin counts via num_bins(). Do not read
    _seconds directly or store a separate int bin count.
    """

    MIN_BINS = 20  # floor on zoom-in; viewport never narrower than 20 * NUDGE_SECONDS

    def __init__(self, seconds: float):
        self._seconds = seconds

    def num_bins(self, song_duration: float) -> int:
        max_bins = max(self.MIN_BINS, int(song_duration / NUDGE_SECONDS))
        bins = round(self._seconds / NUDGE_SECONDS)
        return max(self.MIN_BINS, min(bins, max_bins))

    def zoom(self, factor: float, song_duration: float) -> None:
        """factor > 1 zooms out (wider viewport); < 1 zooms in."""
        min_seconds = self.MIN_BINS * NUDGE_SECONDS
        max_seconds = max(min_seconds, song_duration)
        self._seconds = max(min_seconds, min(self._seconds * factor, max_seconds))


class WaveformWidget(QWidget):

    def __init__(self):
        super().__init__()
        self.player = None
        self._zoom = ViewportZoom(DEFAULT_VIEWPORT_SECONDS)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip("Click to seek. Hold Shift to snap to the nearest beat. Scroll up/down to zoom.")
        # Mouse pixel x while hovering over the widget, or None when the
        # cursor is elsewhere. Resolved to a global bin in paintEvent so the
        # hover line tracks the mouse (not the song content) as playback scrolls.
        self._hover_mouse_x = None

    def mouseMoveEvent(self, event):
        new_x = event.position().x()
        if new_x != self._hover_mouse_x:
            self._hover_mouse_x = new_x
            self.update()

    def leaveEvent(self, event):
        if self._hover_mouse_x is not None:
            self._hover_mouse_x = None
            self.update()

    def wheelEvent(self, event):
        if self.player is None:
            return super().wheelEvent(event)
        delta = event.angleDelta().y()
        if delta == 0:
            return super().wheelEvent(event)
        factor = ZOOM_WHEEL_FACTOR_PER_NOTCH ** (-delta / 120.0)
        self._zoom.zoom(factor, self.player.song_duration)
        event.accept()
        self.update()

    def _target_col_for_x(self, x, wd, modifiers):
        col = x / self.width() * wd.num_bins
        global_bin = wd.viewport_start_bin + col
        if not (0 <= global_bin < wd.total_bins):
            return None

        if modifiers & SNAP_MODIFIER:
            beat_cols = wd.beat_cols + wd.downbeat_cols
            if beat_cols:
                col = min(beat_cols, key=lambda beat_col: abs(beat_col - col))
        return col

    def mousePressEvent(self, event):
        if self.player is None or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        if self.width() < 10:
            return
        wd = self.player.waveform_bins(self._zoom.num_bins(self.player.song_duration))
        target_col = self._target_col_for_x(event.position().x(), wd, event.modifiers())
        if target_col is None:
            return
        target_seconds = (wd.viewport_start_bin + target_col) * NUDGE_SECONDS
        delta = target_seconds - self.player.playback_position
        self.player.seek(delta)
        self.update()

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        top_pad = WAVEFORM_PAD_TOP
        bottom_pad = WAVEFORM_PAD_BOTTOM
        inner_h = h - top_pad - bottom_pad
        mid = top_pad + inner_h // 2
        ruler_y = h - bottom_pad // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        painter.fillRect(0, 0, w, h, WAVEFORM_BG)

        if self.player is None or w < 10:
            painter.end()
            return

        wd = self.player.waveform_bins(self._zoom.num_bins(self.player.song_duration))
        bar_w = w / wd.num_bins

        # Per-pixel envelope avoids subpixel aliasing when num_bins > w:
        # a per-bin loop with int() rounding would only draw bins that
        # straddle a pixel boundary, and which bins those are shifts as
        # bin_offset slides — visible as shimmer during playback.
        # We use peak (max), not mean: mean smooths the residual shimmer
        # more but flattens the waveform — quiet/loud passages look alike
        # and drum hits disappear. We tried both; max's mild residual
        # shimmer is worth the better visual character.
        peaks = _peak_per_pixel(wd.bins, w, wd.bin_offset)
        painter.setPen(Qt.NoPen)
        painter.setBrush(WAVEFORM_COLOR)
        for x in range(w):
            half_h = int(peaks[x] * inner_h / 2)
            if half_h > 0:
                painter.drawRect(x, mid - half_h, 1, half_h * 2)

        def col_to_x(col):
            return int(col * bar_w)

        ruler_pen = QPen(BEAT_RULER_COLOR, 1)
        painter.setPen(ruler_pen)
        painter.drawLine(0, ruler_y, w, ruler_y)

        beat_pen = QPen(BEAT_TICK_COLOR, 1)
        painter.setPen(beat_pen)
        for col in wd.beat_cols:
            x = col_to_x(col)
            painter.drawLine(x, ruler_y - BEAT_TICK_H, x, ruler_y)

        downbeat_pen = QPen(DOWNBEAT_TICK_COLOR, 2)
        painter.setPen(downbeat_pen)
        for col in wd.downbeat_cols:
            x = col_to_x(col)
            painter.drawLine(x, ruler_y - DOWNBEAT_TICK_H, x, ruler_y)

        ls_x = col_to_x(wd.loop_start_col) if wd.loop_start_col is not None else None
        le_x = col_to_x(wd.loop_end_col) if wd.loop_end_col is not None else None

        if wd.loop_active:
            fill_l = ls_x if ls_x is not None else 0
            fill_r = le_x if le_x is not None else w
            painter.fillRect(fill_l, 0, fill_r - fill_l, h, LOOP_FILL_COLOR)

        pen = QPen(LOOP_MARKER_COLOR, 2)
        painter.setPen(pen)
        top = top_pad
        bot = ruler_y
        if ls_x is not None:
            painter.drawLine(ls_x, top, ls_x, bot)
            painter.drawLine(ls_x, top, ls_x + LOOP_SERIF, top)
            painter.drawLine(ls_x, bot, ls_x + LOOP_SERIF, bot)
        if le_x is not None:
            painter.drawLine(le_x, top, le_x, bot)
            painter.drawLine(le_x, top, le_x - LOOP_SERIF, top)
            painter.drawLine(le_x, bot, le_x - LOOP_SERIF, bot)

        # Hover indicator: anchored to the mouse position rather than the song
        # content, so it stays under the cursor as playback scrolls past.
        # With the snap modifier held, it moves to the nearest beat marker.
        # Only drawn when the target is within the seekable range.
        if self._hover_mouse_x is not None:
            target_col = self._target_col_for_x(self._hover_mouse_x, wd, QApplication.keyboardModifiers())
            if target_col is not None:
                pen = QPen(HOVER_COLOR, 1)
                painter.setPen(pen)
                hx = col_to_x(target_col)
                painter.drawLine(hx, 0, hx, h)

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

        start_btn = ActionButton("Set Loop Start", "[", minWidth=LOOP_W, icon_name="loop-start")
        start_btn.clicked.connect(lambda: self._cmd(lambda p: p.set_loop_start()))
        row.addWidget(start_btn)

        end_btn = ActionButton("Set Loop End", "]", minWidth=LOOP_W, icon_name="loop-end")
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

        self._mode_buttons = {}
        for mode, key, icon in [
            ("solo", "1", "solo"),
            ("backing", "2", "backing"),
            ("mix", "3", "mix"),
        ]:
            btn = ActionButton(mode.capitalize(), key, minWidth=LOOP_W, icon_name=icon)
            btn.clicked.connect(lambda _, m=mode: self._cmd(lambda p: p.set_mode(m)))
            row.addWidget(btn)
            self._mode_buttons[mode] = btn

        row.addSpacing(16)

        self.mode_status = QLabel("")
        self.mode_status.setMinimumWidth(90)
        row.addWidget(self.mode_status)

        row.addStretch()
        layout.addLayout(row)

        self._build_click(layout)

    def _build_click(self, layout):
        row = QHBoxLayout()

        self.click_btn = ActionButton("Enable Click", "B", minWidth=LOOP_W, icon_name="metronome")
        self.click_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_click()))
        row.addWidget(self.click_btn)

        row.addSpacing(16)

        self.click_status = QLabel("")
        self.click_status.setMinimumWidth(160)
        row.addWidget(self.click_status)

        row.addSpacing(16)

        self.count_in_btn = ActionButton("Enable Count", "N", minWidth=LOOP_W, icon_name="drumsticks")
        self.count_in_btn.clicked.connect(lambda: self._cmd(lambda p: p.toggle_count_in()))
        row.addWidget(self.count_in_btn)

        row.addSpacing(16)

        self.count_in_status = QLabel("")
        self.count_in_status.setMinimumWidth(200)
        row.addWidget(self.count_in_status)

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
        for mode, btn in self._mode_buttons.items():
            btn.setEnabled(mode != p.mode)
        self.mode_status.setText(f"<b>Play mode:</b> {p.mode}")

        self.click_btn.set_action("Disable Click" if p.click_active else "Enable Click", icon_name="metronome")
        self.click_btn.setEnabled(p._click_track is not None)
        self.count_in_btn.set_action("Disable Count" if p.count_in_enabled else "Enable Count", icon_name="drumsticks")
        self.count_in_btn.setEnabled(p._count_in_track is not None)
        self.click_status.setText(f"<b>Click:</b> {'on' if p.click_active else 'off'}")
        self.count_in_status.setText(f"<b>Count-in:</b> {'on' if p.count_in_enabled else 'off'}")

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
            Qt.Key_1: lambda: self.player.set_mode("solo"),
            Qt.Key_2: lambda: self.player.set_mode("backing"),
            Qt.Key_3: lambda: self.player.set_mode("mix"),
            Qt.Key_H: lambda: self.player.toggle_hold(),
            Qt.Key_L: lambda: self.player.toggle_loop(),
            Qt.Key_B: lambda: self.player.toggle_click(),
            Qt.Key_N: lambda: self.player.toggle_count_in(),
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
