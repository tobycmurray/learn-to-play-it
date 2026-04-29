import sys
import tty
import termios
import select
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from .audio import load_all_stems, mix_stems, process_audio

SPEED_MIN = 0.2
SPEED_MAX = 1.5
SPEED_STEP = 0.1
PITCH_STEP = 10
PITCH_MIN = -200
PITCH_MAX = 200
SEEK_SECONDS = 5
NUDGE_SECONDS = 0.05
HOLD_DURATION = 0.2


@dataclass
class LoopRegion:
    start_orig: int | None = None
    end_orig: int | None = None
    active: bool = False

    def set_start(self, pos: int):
        self.start_orig = pos
        self._enforce()

    def set_end(self, pos: int):
        self.end_orig = pos
        self._enforce()

    def _enforce(self):
        """Ensure start < end. If not, clear the violated bound and deactivate."""
        if self.start_orig is not None and self.end_orig is not None:
            if self.start_orig >= self.end_orig:
                self.end_orig = None
                self.active = False
        if self.start_orig is None or self.end_orig is None:
            self.active = False

    def is_complete(self) -> bool:
        return self.start_orig is not None and self.end_orig is not None


@dataclass
class HoldState:
    start_orig: int
    end_orig: int
    slice: np.ndarray
    pos: int = 0


def _read_key(timeout=0.1):
    """Read a single keypress, or return None after timeout."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if select.select([sys.stdin], [], [], timeout)[0]:
            return sys.stdin.read(1)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class Player:
    """Interactive audio player with speed/pitch/loop/hold controls.

    Position tracking: all position state is stored in original-song sample
    units (self.pos_orig). Buffer indices are derived on the fly via
    _buf_pos(). This avoids dual-position sync bugs when speed changes.

    Threading: the sounddevice callback runs on a separate thread and reads
    self.playing, self.pos_orig, self.audio, self.hold. The GIL protects
    against torn object reads. We set self.playing=False before mutating
    shared arrays so the callback outputs silence during rebuilds.
    """

    def __init__(self, stems_dir, part, initial_mode="solo", initial_speed=0.5):
        self.stems, self.sr = load_all_stems(stems_dir)
        self.part = part
        self.mode = initial_mode
        self.speed = initial_speed
        self.cents = 0.0

        self.audio = None
        self._rebuild()

        self.pos_orig = 0
        self.playing = False
        self.quit = False
        self.stream = None

        self.loop: LoopRegion | None = None
        self.hold: HoldState | None = None

    def _rebuild(self):
        """Recompute the stretched/shifted audio buffer from sources of truth."""
        raw = mix_stems(self.stems, self.mode, self.part)
        self.audio = process_audio(raw, self.sr, self.speed, self.cents)

    def _buf_pos(self, orig_pos: int | None = None) -> int:
        """Convert original-song sample position to buffer index."""
        if orig_pos is None:
            orig_pos = self.pos_orig
        return int(orig_pos / self.speed)

    def _orig_pos(self, buf_pos: int) -> int:
        """Convert buffer index to original-song sample position."""
        return int(buf_pos * self.speed)

    def _buf_len(self) -> int:
        return len(self.audio)

    def _callback(self, outdata, frames, time_info, status):
        if not self.playing:
            outdata[:] = 0
            return

        hold = self.hold
        if hold is not None:
            hold_len = len(hold.slice)
            written = 0
            while written < frames:
                chunk = min(frames - written, hold_len - hold.pos)
                outdata[written:written + chunk] = hold.slice[hold.pos:hold.pos + chunk]
                hold.pos = (hold.pos + chunk) % hold_len
                written += chunk
            return

        buf_pos = self._buf_pos()
        limit = self._buf_len()

        loop = self.loop
        if loop is not None and loop.active and loop.end_orig is not None:
            loop_end_buf = self._buf_pos(loop.end_orig)
            limit = min(limit, loop_end_buf)

        end = buf_pos + frames
        if end <= limit:
            outdata[:] = self.audio[buf_pos:end]
            self.pos_orig = self._orig_pos(end)
        else:
            valid = limit - buf_pos
            if valid > 0:
                outdata[:valid] = self.audio[buf_pos:buf_pos + valid]
            outdata[max(0, valid):] = 0

            if loop is not None and loop.active and loop.end_orig is not None:
                self.pos_orig = loop.start_orig
            else:
                self.pos_orig = self._orig_pos(limit)
                self.playing = False

    def _print_status(self):
        original_secs = self.pos_orig / self.sr
        total_secs = len(list(self.stems.values())[0]) / self.sr
        if self.hold is not None:
            state = "⏺"
        elif self.playing:
            state = "▶"
        else:
            state = "⏸"
        speed_pct = int(round(self.speed * 100))
        cents_str = f"{self.cents:+.0f}" if self.cents != 0 else "0"

        loop = self.loop
        if loop is not None and (loop.start_orig is not None or loop.end_orig is not None):
            ls_str = f"{loop.start_orig / self.sr:.2f}s" if loop.start_orig is not None else "?"
            le_str = f"{loop.end_orig / self.sr:.2f}s" if loop.end_orig is not None else "?"
            loop_str = f"loop: {'ON' if loop.active else 'OFF'} {ls_str}-{le_str}"
        else:
            loop_str = "loop: OFF"

        print(
            f"\r  {state} {original_secs:5.2f}s / {total_secs:.2f}s  |  "
            f"speed: {speed_pct}%  |  pitch: {cents_str}c  |  "
            f"{loop_str}  |  "
            f"mode: {self.mode}  |  part: {self.part}     ",
            end="", flush=True,
        )

    def run(self):
        print(f"Playing: {self.part} ({self.mode})")
        print("Controls: SPACE=play/pause  W/X=speed  E/C=pitch  A/D=seek  Z/V=nudge  H=hold")
        print("          [/]=loop start/end  L=loop  S=mode  0=restart  Q=quit")
        print()

        self.stream = sd.OutputStream(
            samplerate=self.sr,
            channels=self.audio.shape[1] if self.audio.ndim > 1 else 1,
            callback=self._callback,
            blocksize=2048,
        )
        self.stream.start()
        self.playing = True

        try:
            while not self.quit:
                self._print_status()
                key = _read_key()
                if key is not None:
                    self._handle_key(key)
        finally:
            self.stream.stop()
            self.stream.close()
            print()

    def _pause_rebuild_resume(self, reason="processing"):
        """Pause playback, rebuild audio buffer, rebuild hold if active, resume."""
        was_playing = self.playing
        self.playing = False
        print(f"\r  ({reason}...){'':40}", end="", flush=True)
        self._rebuild()
        if self.hold is not None:
            self._rebuild_hold_slice()
        self.playing = was_playing

    def _rebuild_hold_slice(self):
        hold = self.hold
        if hold is None:
            return
        buf_start = self._buf_pos(hold.start_orig)
        buf_end = self._buf_pos(hold.end_orig)
        hold.slice = self.audio[buf_start:buf_end].copy()
        hold.pos = 0

    def _change_speed(self, delta):
        new_speed = round(min(SPEED_MAX, max(SPEED_MIN, self.speed + delta)), 2)
        if new_speed == self.speed:
            return
        self.speed = new_speed
        self._pause_rebuild_resume("stretching")

    def _change_pitch(self, delta):
        new_cents = min(PITCH_MAX, max(PITCH_MIN, self.cents + delta))
        if new_cents == self.cents:
            return
        self.cents = new_cents
        self._pause_rebuild_resume("pitch-shifting")

    def _change_mode(self):
        modes = ["solo", "mute", "mix"]
        idx = (modes.index(self.mode) + 1) % len(modes)
        self.mode = modes[idx]
        self._pause_rebuild_resume("switching mode")

    def _seek(self, seconds):
        delta_orig = int(seconds * self.sr)
        new_pos = self.pos_orig + delta_orig

        loop = self.loop
        if loop is not None and loop.active and loop.end_orig is not None:
            new_pos = max(loop.start_orig, min(new_pos, loop.end_orig - 1))
        else:
            max_orig = self._orig_pos(self._buf_len() - 1)
            new_pos = max(0, min(new_pos, max_orig))

        self.pos_orig = new_pos

    def _set_loop_start(self):
        if self.loop is None:
            self.loop = LoopRegion()
        self.loop.set_start(self.pos_orig)

    def _set_loop_end(self):
        if self.loop is None:
            self.loop = LoopRegion()
        self.loop.set_end(self.pos_orig)

    def _toggle_loop(self):
        loop = self.loop
        if loop is None or not loop.is_complete():
            return
        loop.active = not loop.active
        if loop.active:
            if self.pos_orig >= loop.end_orig or self.pos_orig < loop.start_orig:
                self.pos_orig = loop.start_orig

    def _toggle_hold(self):
        if self.hold is not None:
            self.pos_orig = self.hold.end_orig
            self.hold = None
        else:
            hold_orig_samples = int(HOLD_DURATION * self.sr)
            start = max(0, self.pos_orig - hold_orig_samples)
            end = self.pos_orig
            buf_start = self._buf_pos(start)
            buf_end = self._buf_pos(end)
            slice_data = self.audio[buf_start:buf_end].copy()
            if len(slice_data) == 0:
                return
            self.hold = HoldState(start_orig=start, end_orig=end, slice=slice_data)

    def _handle_key(self, key):
        if key == " ":
            self.playing = not self.playing
        elif key.lower() == "q":
            self.quit = True
        elif key == "0":
            loop = self.loop
            if loop is not None and loop.active:
                self.pos_orig = loop.start_orig
            else:
                self.pos_orig = 0
        elif key.lower() == "s":
            self._change_mode()
        elif key.lower() == "w":
            self._change_speed(SPEED_STEP)
        elif key.lower() == "x":
            self._change_speed(-SPEED_STEP)
        elif key.lower() == "e":
            self._change_pitch(PITCH_STEP)
        elif key.lower() == "c":
            self._change_pitch(-PITCH_STEP)
        elif key.lower() == "a":
            self._seek(-SEEK_SECONDS)
        elif key.lower() == "d":
            self._seek(SEEK_SECONDS)
        elif key.lower() == "z":
            self._seek(-NUDGE_SECONDS)
        elif key.lower() == "v":
            self._seek(NUDGE_SECONDS)
        elif key.lower() == "h":
            self._toggle_hold()
        elif key == "[":
            self._set_loop_start()
        elif key == "]":
            self._set_loop_end()
        elif key.lower() == "l":
            self._toggle_loop()


def play_interactive(stems_dir, part, initial_mode="solo", initial_speed=0.5):
    player = Player(stems_dir, part, initial_mode, initial_speed)
    player.run()
