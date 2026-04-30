import os
import sys
import tty
import termios
import select
import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from pylibrb import RubberBandStretcher, Option

from .audio import load_all_stems, mix_stems
from .ringbuffer import RingBuffer

SPEED_MIN = 0.2
SPEED_MAX = 1.5
SPEED_STEP = 0.1
PITCH_STEP = 10
PITCH_MIN = -1200 # allow for a full octave either way
PITCH_MAX = 1200
SEEK_SECONDS = 5
NUDGE_SECONDS = 0.05
HOLD_DURATION = 0.4

BLOCK_SIZE = 1024
RING_CAPACITY = 16384
MODES = ["solo", "mute", "mix"]

WAVEFORM_BLOCKS = " ▁▂▃▄▅▆▇█"
WAVEFORM_ROWS = 8
# status line + waveform rows + marker row
DISPLAY_LINES = 1 + WAVEFORM_ROWS + 1


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
    raw: np.ndarray
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
    """Interactive audio player with real-time speed/pitch/loop/hold controls.

    Architecture: a feeder thread reads raw audio, pushes it through a
    RubberBandStretcher in real-time mode, and writes to a ring buffer.
    The sounddevice callback reads from the ring buffer. Speed/pitch
    changes take effect within one block (~23ms) with no pause.
    """

    def __init__(self, stems_dir, part, initial_mode="solo", initial_speed=0.5, initial_cents=0.0, device=None):
        self.stems, self.sr = load_all_stems(stems_dir)
        self.part = part
        self.mode = initial_mode
        self.speed = initial_speed
        self.cents = initial_cents

        self.mixes = {
            "solo": mix_stems(self.stems, "solo", part),
            "mute": mix_stems(self.stems, "mute", part),
            "mix": mix_stems(self.stems, "mix", part),
        }
        self.channels = self.mixes["solo"].shape[1] if self.mixes["solo"].ndim > 1 else 1
        self.song_len = len(self.mixes["solo"])
        self.mix_peaks = {mode: self._compute_rms_peak(mix) for mode, mix in self.mixes.items()}

        self.ring = RingBuffer(RING_CAPACITY, self.channels)
        self.stretcher = self._make_stretcher()

        self.pos_orig = 0
        self.device = device
        self.playing = False
        self.quit = False
        self.stream = None

        self.loop: LoopRegion | None = None
        self.hold: HoldState | None = None

        self._seek_requested = False
        self._feeder_stop = threading.Event()
        self._feeder_paused = False
        self._feeder_thread = None

    def _compute_rms_peak(self, mix):
        bin_samples = int(NUDGE_SECONDS * self.sr)
        mono = np.abs(mix).max(axis=1) if mix.ndim > 1 else np.abs(mix.ravel())
        n_bins = len(mono) // bin_samples
        if n_bins == 0:
            return 1.0
        trimmed = mono[:n_bins * bin_samples].reshape(n_bins, bin_samples)
        rms = np.sqrt(np.mean(trimmed ** 2, axis=1))
        return float(rms.max()) or 1.0

    @property
    def _playback_pos(self):
        """Estimated position of audio currently being heard by the user.

        The feeder runs ahead of playback — the ring buffer holds stretched
        audio that hasn't reached the speakers yet. We subtract that to
        approximate what's actually playing.
        """
        buffered_orig = int(self.ring.available() * self.speed)
        return max(0, self.pos_orig - buffered_orig)

    @property
    def _time_ratio(self):
        return 1.0 / self.speed

    @property
    def _pitch_scale(self):
        return 2.0 ** (self.cents / 1200.0)

    def _make_stretcher(self):
        s = RubberBandStretcher(
            sample_rate=self.sr,
            channels=self.channels,
            options=Option.PROCESS_REALTIME | Option.ENGINE_FINER | Option.PitchHighConsistency,
            initial_time_ratio=self._time_ratio,
            initial_pitch_scale=self._pitch_scale,
        )
        s.set_max_process_size(BLOCK_SIZE)
        return s

    def _feeder_reset(self):
        self.ring.flush()
        self.stretcher = self._make_stretcher()

    def _feeder_loop(self):
        while not self._feeder_stop.is_set():
            if self._feeder_paused:
                self._feeder_stop.wait(0.01)
                continue

            if self._seek_requested:
                self._feeder_reset()
                self._seek_requested = False

            if not self.playing:
                self._feeder_stop.wait(0.01)
                continue

            self.stretcher.time_ratio = self._time_ratio
            self.stretcher.pitch_scale = self._pitch_scale

            mix = self.mixes[self.mode]
            pos = self.pos_orig
            end_pos = self.song_len

            loop = self.loop
            if loop is not None and loop.active and loop.end_orig is not None:
                end_pos = loop.end_orig

            if pos >= end_pos:
                if loop is not None and loop.active and loop.start_orig is not None:
                    self.pos_orig = loop.start_orig
                    continue
                self._feeder_stop.wait(0.01)
                continue

            if self.ring.free() < BLOCK_SIZE * 4:
                self._feeder_stop.wait(0.005)
                continue

            block_size = min(BLOCK_SIZE, end_pos - pos)
            block = mix[pos:pos + block_size]
            self.stretcher.process(block.T, final=False)
            output = self.stretcher.retrieve_available()
            if output.shape[1] > 0:
                self.ring.write(output.T)

            self.pos_orig = pos + block_size

    def _callback(self, outdata, frames, time_info, status):
        if not self.playing:
            outdata[:] = 0
            return

        hold = self.hold
        if hold is not None:
            hold_len = len(hold.slice)
            if hold_len == 0:
                outdata[:] = 0
                return
            written = 0
            while written < frames:
                chunk = min(frames - written, hold_len - hold.pos)
                outdata[written:written + chunk] = hold.slice[hold.pos:hold.pos + chunk]
                hold.pos = (hold.pos + chunk) % hold_len
                written += chunk
            return

        avail = self.ring.available()
        if avail >= frames:
            data = self.ring.read(frames)
            outdata[:] = data
        elif avail > 0:
            data = self.ring.read(avail)
            outdata[:avail] = data
            outdata[avail:] = 0
        else:
            outdata[:] = 0
            if self.pos_orig >= self.song_len:
                self.playing = False

    @staticmethod
    def _fmt_time(secs):
        m, s = divmod(secs, 60)
        return f"{int(m)}:{s:05.2f}"

    def _status_text(self):
        original_secs = self._playback_pos / self.sr
        total_secs = self.song_len / self.sr
        if self.hold is not None:
            state = "⏺"
        elif self.playing:
            state = "▶"
        else:
            state = "⏸"
        speed_pct = int(round(self.speed * 100))

        c = round(self.cents)
        if c == 0:
            cents_str = "0c"
        elif abs(c) < 100:
            cents_str = f"{c:+}c"
        else:
            st = int(c / 100)
            rem = c - st * 100
            cents_str = f"{st:+}st" if rem == 0 else f"{st:+}st{rem:+}c"

        loop = self.loop
        if loop is not None and (loop.start_orig is not None or loop.end_orig is not None):
            ls_str = self._fmt_time(loop.start_orig / self.sr) if loop.start_orig is not None else "?"
            le_str = self._fmt_time(loop.end_orig / self.sr) if loop.end_orig is not None else "?"
            loop_str = f"loop: {'ON' if loop.active else 'OFF'} {ls_str}-{le_str}"
        else:
            loop_str = "loop: OFF"

        return (
            f"  {state} {self._fmt_time(original_secs)} / {self._fmt_time(total_secs)}  |  "
            f"speed: {speed_pct}%  |  pitch: {cents_str}  |  "
            f"{loop_str}  |  "
            f"mode: {self.mode}  |  part: {self.part}"
        )

    def _waveform_bins(self, waveform_width):
        bin_samples = int(NUDGE_SECONDS * self.sr)
        half = waveform_width // 2
        window_start = self._playback_pos - half * bin_samples

        mix = self.mixes[self.mode]
        end = window_start + waveform_width * bin_samples
        pad_left = max(0, -window_start)
        pad_right = max(0, end - self.song_len)
        segment = mix[max(0, window_start):min(self.song_len, end)]
        if self.channels > 1:
            segment = np.abs(segment).max(axis=1)
        else:
            segment = np.abs(segment.ravel())
        if pad_left > 0 or pad_right > 0:
            segment = np.concatenate([
                np.zeros(pad_left, dtype=np.float32),
                segment,
                np.zeros(pad_right, dtype=np.float32),
            ])

        bins = np.array([
            np.sqrt(np.mean(segment[i * bin_samples:(i + 1) * bin_samples] ** 2))
            for i in range(waveform_width)
        ])
        bins /= self.mix_peaks[self.mode]
        np.clip(bins, 0, 1, out=bins)
        return bins, half, window_start, bin_samples

    @staticmethod
    def _bins_to_rows(bins):
        levels = len(WAVEFORM_BLOCKS) - 1
        rows = []
        for row in range(WAVEFORM_ROWS - 1, -1, -1):
            threshold = row / WAVEFORM_ROWS
            next_threshold = (row + 1) / WAVEFORM_ROWS
            line = []
            for v in bins:
                if v >= next_threshold:
                    line.append(WAVEFORM_BLOCKS[-1])
                elif v > threshold:
                    frac = (v - threshold) / (next_threshold - threshold)
                    line.append(WAVEFORM_BLOCKS[max(1, int(frac * levels))])
                else:
                    line.append(" ")
            rows.append("".join(line))
        return rows

    def _marker_line(self, width, cursor_col, window_start, bin_samples):
        markers = [" "] * width
        markers[cursor_col] = "↑"
        loop = self.loop
        if loop is not None:
            for pos, char in [(loop.start_orig, "["), (loop.end_orig, "]")]:
                if pos is not None:
                    col = (pos - window_start) // bin_samples
                    if 0 <= col < width:
                        markers[col] = char
        return "  " + "".join(markers)

    def _print_status(self):
        term_width = os.get_terminal_size().columns
        status = self._status_text()[:term_width].ljust(term_width)

        show_waveform = not self.playing and self.hold is None
        waveform_width = term_width - 4

        if show_waveform and waveform_width >= 10:
            bins, cursor_col, window_start, bin_samples = self._waveform_bins(waveform_width)
            rows = self._bins_to_rows(bins)
            markers = self._marker_line(waveform_width, cursor_col, window_start, bin_samples)
            body = [f"  {row}"[:term_width] for row in rows] + [markers[:term_width]]
        else:
            if show_waveform:
                hint = "  (widen terminal to see waveform)"
            elif self.hold is not None:
                hint = "  (hold active — H to release)"
            else:
                hint = "  (SPACE to pause and show waveform)"
            blank = "".ljust(term_width)
            body = [blank] * (DISPLAY_LINES - 1)
            body[WAVEFORM_ROWS // 2] = hint[:term_width].ljust(term_width)

        assert len(body) == DISPLAY_LINES - 1
        lines = [status] + body
        print("\r" + "\n".join(lines), end="", flush=True)
        print(f"\033[{DISPLAY_LINES - 1}A\r", end="", flush=True)

    def run(self):
        print(f"Playing: {self.part} ({self.mode})")
        print("Controls: SPACE=play/pause  W/S=speed  E/D=pitch  Z/X/C/V=seek  H=hold")
        print("          [/]=loop start/end  L=loop  M=mode  0=restart  Q=quit")
        print()

        self.stream = sd.OutputStream(
            samplerate=self.sr,
            channels=self.channels,
            callback=self._callback,
            blocksize=2048,
            device=self.device,
        )
        self.stream.start()

        self._feeder_thread = threading.Thread(target=self._feeder_loop, daemon=True)
        self._feeder_thread.start()

        self.playing = True

        try:
            while not self.quit:
                self._print_status()
                key = _read_key()
                if key is not None:
                    self._handle_key(key)
        finally:
            self._feeder_stop.set()
            self._feeder_thread.join(timeout=2)
            self.stream.stop()
            self.stream.close()
            print()

    def _change_speed(self, delta):
        new_speed = round(min(SPEED_MAX, max(SPEED_MIN, self.speed + delta)), 2)
        if new_speed == self.speed:
            return
        self.speed = new_speed
        self._rebuild_hold_slice()

    def _change_pitch(self, delta):
        new_cents = min(PITCH_MAX, max(PITCH_MIN, self.cents + delta))
        if new_cents == self.cents:
            return
        self.cents = new_cents
        self._rebuild_hold_slice()

    def _change_mode(self):
        idx = (MODES.index(self.mode) + 1) % len(MODES)
        self.mode = MODES[idx]

    def _seek(self, seconds):
        if self.hold is not None:
            return
        delta_orig = int(seconds * self.sr)
        new_pos = self._playback_pos + delta_orig

        loop = self.loop
        if loop is not None and loop.active and loop.end_orig is not None:
            new_pos = max(loop.start_orig, min(new_pos, loop.end_orig - 1))
        else:
            new_pos = max(0, min(new_pos, self.song_len - 1))

        self.pos_orig = new_pos
        self._seek_requested = True

    def _set_loop_start(self):
        if self.loop is None:
            self.loop = LoopRegion()
        self.loop.set_start(self._playback_pos)

    def _set_loop_end(self):
        if self.loop is None:
            self.loop = LoopRegion()
        self.loop.set_end(self._playback_pos)

    def _toggle_loop(self):
        loop = self.loop
        if loop is None or not loop.is_complete():
            return
        loop.active = not loop.active
        if loop.active:
            if self._playback_pos >= loop.end_orig or self._playback_pos < loop.start_orig:
                self.pos_orig = loop.start_orig
                self._seek_requested = True

    def _process_hold_raw(self, raw: np.ndarray) -> np.ndarray:
        s = self._make_stretcher()
        s.process(raw.T, final=True)
        return s.retrieve_available().T

    def _rebuild_hold_slice(self):
        hold = self.hold
        if hold is None:
            return
        processed = self._process_hold_raw(hold.raw)
        if len(processed) > 0:
            hold.slice = processed
            hold.pos = 0

    def _toggle_hold(self):
        if self.hold is not None:
            self.pos_orig = self.hold.end_orig
            self.hold = None
            self._feeder_paused = False
            self._seek_requested = True
        else:
            hold_orig_samples = int(HOLD_DURATION * self.sr)
            end = self._playback_pos
            start = max(0, end - hold_orig_samples)
            if end <= start:
                return
            raw = self.mixes[self.mode][start:end]
            processed = self._process_hold_raw(raw)
            if len(processed) == 0:
                return
            self.hold = HoldState(start_orig=start, end_orig=end, raw=raw, slice=processed)
            self._feeder_paused = True

    def _handle_key(self, key):
        if key == " ":
            self.playing = not self.playing
        elif key.lower() == "q":
            self.quit = True
        elif key == "0":
            if self.hold is not None:
                return
            loop = self.loop
            if loop is not None and loop.active:
                self.pos_orig = loop.start_orig
            else:
                self.pos_orig = 0
            self._seek_requested = True
        elif key.lower() == "w":
            self._change_speed(SPEED_STEP)
        elif key.lower() == "s":
            self._change_speed(-SPEED_STEP)
        elif key.lower() == "e":
            self._change_pitch(PITCH_STEP)
        elif key.lower() == "d":
            self._change_pitch(-PITCH_STEP)
        elif key.lower() == "z":
            self._seek(-SEEK_SECONDS)
        elif key.lower() == "x":
            self._seek(-NUDGE_SECONDS)
        elif key.lower() == "c":
            self._seek(NUDGE_SECONDS)
        elif key.lower() == "v":
            self._seek(SEEK_SECONDS)
        elif key.lower() == "m":
            self._change_mode()
        elif key.lower() == "h":
            self._toggle_hold()
        elif key == "[":
            self._set_loop_start()
        elif key == "]":
            self._set_loop_end()
        elif key.lower() == "l":
            self._toggle_loop()


def play_interactive(stems_dir, part, initial_mode="solo", initial_speed=0.5, initial_cents=0.0, device=None):
    player = Player(stems_dir, part, initial_mode, initial_speed, initial_cents, device=device)
    player.run()
