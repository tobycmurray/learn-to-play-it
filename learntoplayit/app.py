import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog,
    QDialog, QDialogButtonBox, QRadioButton, QButtonGroup,
    QProgressDialog, QMessageBox, QSpinBox, QFrame, QComboBox,
)

from .fmt import fmt_pitch
from .gui import PlayerWidget, WINDOW_MIN_W, WINDOW_W, WINDOW_H
from .player import (
    SPEED_STEP, PITCH_STEP, SEEK_SECONDS, NUDGE_SECONDS,
    SPEED_MIN, SPEED_MAX, PITCH_MIN, PITCH_MAX,
)
from .separate import STEM_NAMES


APP_NAME = "Learn To Play It"

def add_bundled_bin_to_path():
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        bundled_bin = exe_dir.parent / "Frameworks" / "bin"

        if bundled_bin.exists():
            os.environ["PATH"] = str(bundled_bin) + os.pathsep + os.environ.get("PATH", "")

def default_stems_root():
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path.cwd()

    stems = base / "stems"
    stems.mkdir(parents=True, exist_ok=True)
    return stems

class PitchSpinBox(QSpinBox):
    def textFromValue(self, value):
        return fmt_pitch(value)


class _StderrCapture:
    """Intercepts stderr to extract tqdm percentage updates."""

    def __init__(self, signal, original):
        self._signal = signal
        self._original = original
        self._buf = ""

    def write(self, text):
        self._original.write(text)
        self._buf += text
        parts = self._buf.split("\r")
        self._buf = parts[-1]
        for part in parts[:-1]:
            m = re.search(r"(\d+)%", part)
            if m:
                self._signal.emit(int(m.group(1)))

    def flush(self):
        self._original.flush()


class SeparationWorker(QThread):
    finished = Signal(str)
    error = Signal(str)
    progress = Signal(int)

    def __init__(self, audio_file):
        super().__init__()
        self.audio_file = audio_file

    def run(self):
        old_stderr = sys.stderr
        sys.stderr = _StderrCapture(self.progress, old_stderr)
        try:
            from .separate import ensure_stems
            stems_dir = ensure_stems(self.audio_file)
            self.finished.emit(str(stems_dir))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            sys.stderr = old_stderr


class BeatDetectionWorker(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, audio_file):
        super().__init__()
        self.audio_file = audio_file

    def run(self):
        try:
            from .beats import ensure_beats
            ensure_beats(self.audio_file)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


PRESETS = {
    "practice": {"mode": "solo", "speed": 50, "label": "Practice — solo at 50% speed"},
    "play_along": {"mode": "backing", "speed": 100, "label": "Play Along — backing track at full speed"},
}


class SetupDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Setup")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Part"))
        self._part_buttons = {}
        for name in STEM_NAMES:
            btn = QRadioButton(name)
            layout.addWidget(btn)
            self._part_buttons[name] = btn
        self._part_buttons[STEM_NAMES[0]].setChecked(True)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        layout.addWidget(QLabel("Mode"))
        self._mode_group = QButtonGroup(self)
        self._practice_btn = QRadioButton(PRESETS["practice"]["label"])
        self._play_along_btn = QRadioButton(PRESETS["play_along"]["label"])
        self._mode_group.addButton(self._practice_btn)
        self._mode_group.addButton(self._play_along_btn)
        self._practice_btn.setChecked(True)
        layout.addWidget(self._practice_btn)
        layout.addWidget(self._play_along_btn)

        self._practice_btn.toggled.connect(self._on_mode_changed)

        row = QHBoxLayout()
        row.addWidget(QLabel("Speed"))
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(int(SPEED_MIN * 100), int(SPEED_MAX * 100))
        self._speed_spin.setSingleStep(int(SPEED_STEP * 100))
        self._speed_spin.setSuffix("%")
        self._speed_spin.setValue(PRESETS["practice"]["speed"])
        row.addWidget(self._speed_spin)

        row.addWidget(QLabel("Pitch"))
        self._pitch_spin = PitchSpinBox()
        self._pitch_spin.setRange(PITCH_MIN, PITCH_MAX)
        self._pitch_spin.setSingleStep(PITCH_STEP)
        self._pitch_spin.setValue(0)
        self._pitch_spin.setMinimumWidth(120)
        self._pitch_spin.lineEdit().setReadOnly(True)
        row.addWidget(self._pitch_spin)

        row.addStretch()
        layout.addLayout(row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("Output Device"))
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(250)
        self._device_combo.addItem("System Default", None)
        import sounddevice as sd
        sd._terminate()
        sd._initialize()
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0:
                self._device_combo.addItem(d["name"], i)
        device_row.addWidget(self._device_combo)
        device_row.addStretch()
        layout.addLayout(device_row)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _on_mode_changed(self):
        preset = PRESETS["practice"] if self._practice_btn.isChecked() else PRESETS["play_along"]
        self._speed_spin.setValue(preset["speed"])

    def selected_part(self):
        for name, btn in self._part_buttons.items():
            if btn.isChecked():
                return name
        return STEM_NAMES[0]

    def selected_mode(self):
        preset = PRESETS["practice"] if self._practice_btn.isChecked() else PRESETS["play_along"]
        return preset["mode"]

    def selected_speed(self):
        return self._speed_spin.value() / 100

    def selected_pitch(self):
        return self._pitch_spin.value()

    def selected_device(self):
        return self._device_combo.currentData()


class AppWindow(QMainWindow):

    def __init__(self, app):
        self.app = app
        super().__init__()

        self.player = None
        self._worker = None
        self._progress = None
        self._audio_file = None
        self._beat_worker = None
        self._beat_progress = None
        self._pending_player_args = None

        self.setWindowTitle("Learn To Play It")
        self.setMinimumWidth(WINDOW_MIN_W)
        self.resize(WINDOW_W, WINDOW_H)

        from .separate import set_stems_root
        set_stems_root(default_stems_root())

        self._build_menu()

        self.welcome = QLabel("Open an audio file to get started.\n\nFile → Open  (⌘O)")
        self.welcome.setAlignment(Qt.AlignCenter)
        self.welcome.setStyleSheet("font-size: 18px; color: gray; padding: 60px;")

        self.player_widget = PlayerWidget()
        self.player_widget.hide()

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(self.welcome)
        vbox.addWidget(self.player_widget)
        self.setCentralWidget(container)

        self._bind_keys()

    def _build_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")

        open_action = QAction("&Open…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _bind_keys(self):
        shortcuts = {
            Qt.Key_Space: lambda: self._cmd(lambda p: p.toggle_play()),
            Qt.Key_0: lambda: self._cmd(lambda p: p.restart()),
            Qt.Key_W: lambda: self._cmd(lambda p: p.change_speed(SPEED_STEP)),
            Qt.Key_S: lambda: self._cmd(lambda p: p.change_speed(-SPEED_STEP)),
            Qt.Key_E: lambda: self._cmd(lambda p: p.change_pitch(PITCH_STEP)),
            Qt.Key_D: lambda: self._cmd(lambda p: p.change_pitch(-PITCH_STEP)),
            Qt.Key_Z: lambda: self._cmd(lambda p: p.seek(-SEEK_SECONDS)),
            Qt.Key_X: lambda: self._cmd(lambda p: p.seek(-NUDGE_SECONDS)),
            Qt.Key_C: lambda: self._cmd(lambda p: p.seek(NUDGE_SECONDS)),
            Qt.Key_V: lambda: self._cmd(lambda p: p.seek(SEEK_SECONDS)),
            Qt.Key_1: lambda: self._cmd(lambda p: p.set_mode("solo")),
            Qt.Key_2: lambda: self._cmd(lambda p: p.set_mode("backing")),
            Qt.Key_3: lambda: self._cmd(lambda p: p.set_mode("mix")),
            Qt.Key_H: lambda: self._cmd(lambda p: p.toggle_hold()),
            Qt.Key_L: lambda: self._cmd(lambda p: p.toggle_loop()),
            Qt.Key_B: lambda: self._cmd(lambda p: p.toggle_click()),
            Qt.Key_BracketLeft: lambda: self._cmd(lambda p: p.set_loop_start()),
            Qt.Key_BracketRight: lambda: self._cmd(lambda p: p.set_loop_end()),
        }
        for key, fn in shortcuts.items():
            QShortcut(QKeySequence(key), self).activated.connect(fn)

    def _cmd(self, fn):
        if self.player is not None:
            fn(self.player)

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Audio File", "",
            "Audio Files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;All Files (*)",
        )
        if not path:
            return

        if shutil.which("ffmpeg") is None:
            QMessageBox.critical(
                self, "Missing Dependency",
                "ffmpeg is required for stem separation.\n\n"
                "Install it with:\n"
                "  brew install ffmpeg  (macOS)\n"
                "  apt install ffmpeg   (Linux)",
            )
            return

        self._start_separation(path)

    def _start_separation(self, audio_file):
        from .separate import stems_exist, get_stems_dir

        if stems_exist(audio_file):
            self._on_stems_ready(str(get_stems_dir(audio_file)), audio_file)
            return

        self._audio_file = audio_file
        self._progress = QProgressDialog(
            "Separating stems…", None, 0, 100, self,
        )
        self._progress.setWindowTitle("Separating")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setCancelButton(None)
        self._progress.setValue(0)
        self._progress.show()

        self._worker = SeparationWorker(audio_file)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.finished.connect(self._on_separation_done)
        self._worker.error.connect(self._on_separation_error)
        self._worker.start()

    def _on_separation_done(self, stems_dir):
        if self._progress:
            self._progress.close()
            self._progress = None
        self._on_stems_ready(stems_dir, self._audio_file)

    def _on_separation_error(self, error_msg):
        if self._progress:
            self._progress.close()
            self._progress = None
        QMessageBox.critical(self, "Separation Failed", f"Error separating stems:\n{error_msg}")

    def _on_stems_ready(self, stems_dir, audio_file):
        dialog = SetupDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._load_player(
            stems_dir, audio_file,
            part=dialog.selected_part(),
            mode=dialog.selected_mode(),
            speed=dialog.selected_speed(),
            pitch=dialog.selected_pitch(),
            device=dialog.selected_device(),
        )

    def _load_player(self, stems_dir, audio_file, part, mode, speed, pitch, device=None):
        if self.player is not None:
            self.player_widget._timer.stop()
            self.player.stop()

        from .beats import beats_exist
        if not beats_exist(audio_file):
            self._pending_player_args = (stems_dir, audio_file, part, mode, speed, pitch, device)
            self._beat_progress = QProgressDialog(
                "Detecting beats…", None, 0, 0, self,
            )
            self._beat_progress.setWindowTitle("Detecting Beats")
            self._beat_progress.setWindowModality(Qt.WindowModal)
            self._beat_progress.setCancelButton(None)
            self._beat_progress.show()

            self._beat_worker = BeatDetectionWorker(audio_file)
            self._beat_worker.finished.connect(self._on_beats_ready)
            self._beat_worker.error.connect(self._on_beats_error)
            self._beat_worker.start()
            return

        self._start_player(stems_dir, audio_file, part, mode, speed, pitch, device)

    def _on_beats_ready(self):
        if self._beat_progress:
            self._beat_progress.close()
            self._beat_progress = None
        args = self._pending_player_args
        self._pending_player_args = None
        if args:
            self._start_player(*args)

    def _on_beats_error(self, error_msg):
        if self._beat_progress:
            self._beat_progress.close()
            self._beat_progress = None
        args = self._pending_player_args
        self._pending_player_args = None
        QMessageBox.warning(self, "Beat Detection Failed", f"Could not detect beats:\n{error_msg}\n\nContinuing without click track.")
        if args:
            self._start_player(*args)

    def _start_player(self, stems_dir, audio_file, part, mode, speed, pitch, device=None):
        from .player import Player
        player = Player(stems_dir, part, initial_mode=mode, initial_speed=speed, initial_cents=pitch, device=device)
        try:
            player.start()
        except Exception as e:
            player.stop()
            QMessageBox.critical(self, "Playback Error", f"Could not start playback:\n{e}")
            return

        self.player = player
        self.player_widget.set_player(self.player)
        self.player_widget._timer.start(50)

        self.welcome.hide()
        self.player_widget.show()

        filename = Path(audio_file).name
        self.setWindowTitle(f"Learn To Play It — {filename} — {part}")

    def closeEvent(self, event):
        if self.player is not None:
            self.player_widget._timer.stop()
            self.player.stop()
        event.accept()


def main():
    import multiprocessing
    multiprocessing.freeze_support()

    add_bundled_bin_to_path()

    app = QApplication(sys.argv)

    window = AppWindow(app)
    window.show()
    sys.exit(app.exec())
