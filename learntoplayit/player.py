import sys
import tty
import termios

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
HOLD_DURATION = 0.2


def _read_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


class Player:
    def __init__(self, stems_dir, part, initial_mode="solo", initial_speed=0.5):
        self.stems, self.sr = load_all_stems(stems_dir)
        self.part = part
        self.mode = initial_mode
        self.speed = initial_speed
        self.cents = 0.0

        self.raw_audio = mix_stems(self.stems, self.mode, self.part)
        self._rebuild_audio()
        self.original_pos = 0.0
        self.pos = 0
        self.playing = False
        self.quit = False
        self.stream = None

        # Loop points in original-song sample positions (speed-independent)
        self.loop_start_orig = None
        self.loop_end_orig = None
        self.looping = False

        # Hold state — positions stored in original-song samples
        self.holding = False
        self.hold_slice = None
        self.hold_pos = 0
        self.hold_start_orig = 0
        self.hold_end_orig = 0

    def _rebuild_audio(self):
        self.audio = process_audio(self.raw_audio, self.sr, self.speed, self.cents)

    def _original_pos_from_buffer(self):
        return self.pos * self.speed

    def _buffer_pos_from_original(self):
        return int(self.original_pos / self.speed)

    def _loop_end_buffer(self):
        if self.loop_end_orig is None:
            return None
        return int(self.loop_end_orig / self.speed)

    def _loop_start_buffer(self):
        if self.loop_start_orig is None:
            return None
        return int(self.loop_start_orig / self.speed)

    def _callback(self, outdata, frames, time_info, status):
        if not self.playing:
            outdata[:] = 0
            return

        if self.holding and self.hold_slice is not None:
            hold_len = len(self.hold_slice)
            written = 0
            while written < frames:
                chunk = min(frames - written, hold_len - self.hold_pos)
                outdata[written:written + chunk] = self.hold_slice[self.hold_pos:self.hold_pos + chunk]
                self.hold_pos = (self.hold_pos + chunk) % hold_len
                written += chunk
            return

        limit = len(self.audio)
        loop_end = self._loop_end_buffer()
        if self.looping and loop_end is not None:
            limit = min(limit, loop_end)

        end = self.pos + frames
        if end <= limit:
            outdata[:] = self.audio[self.pos:end]
            self.pos = end
        else:
            valid = limit - self.pos
            if valid > 0:
                outdata[:valid] = self.audio[self.pos:self.pos + valid]
            outdata[max(0, valid):] = 0

            if self.looping and loop_end is not None:
                loop_start = self._loop_start_buffer() or 0
                self.pos = loop_start
            else:
                self.pos = limit
                self.playing = False

    def _print_status(self):
        original_secs = self._original_pos_from_buffer() / self.sr
        total_secs = len(self.raw_audio) / self.sr
        if self.holding:
            state = "⏺"
        elif self.playing:
            state = "▶"
        else:
            state = "⏸"
        speed_pct = int(round(self.speed * 100))
        cents_str = f"{self.cents:+.0f}" if self.cents != 0 else "0"
        ls_str = f"{self.loop_start_orig / self.sr:.1f}s" if self.loop_start_orig is not None else "none"
        le_str = f"{self.loop_end_orig / self.sr:.1f}s" if self.loop_end_orig is not None else "none"
        if self.looping:
            loop_str = f"loop: ON {ls_str}-{le_str}"
        else:
            loop_str = f"loop: OFF {ls_str}-{le_str}"
        print(
            f"\r  {state} {original_secs:5.1f}s / {total_secs:.1f}s  |  "
            f"speed: {speed_pct}%  |  pitch: {cents_str}c  |  "
            f"{loop_str}  |  "
            f"mode: {self.mode}  |  part: {self.part}     ",
            end="", flush=True,
        )

    def run(self):
        print(f"Playing: {self.part} ({self.mode})")
        print("Controls: SPACE=play/pause  W/X=speed  E/C=pitch  A/D=seek  H=hold")
        print("          [=loop point  L=loop  S=mode  0=restart  Q=quit")
        print()

        self.stream = sd.OutputStream(
            samplerate=self.sr,
            channels=self.raw_audio.shape[1] if self.raw_audio.ndim > 1 else 1,
            callback=self._callback,
            blocksize=2048,
        )
        self.stream.start()
        self.playing = True

        try:
            while not self.quit:
                self._print_status()
                key = _read_key()
                self._handle_key(key)
        finally:
            self.stream.stop()
            self.stream.close()
            print()

    def _rebuild_at_position(self):
        was_playing = self.playing
        self.playing = False
        self._rebuild_audio()
        self.pos = min(self._buffer_pos_from_original(), max(0, len(self.audio) - 1))
        if self.holding:
            self._rebuild_hold_slice()
        self.playing = was_playing

    def _change_speed(self, delta):
        new_speed = round(min(SPEED_MAX, max(SPEED_MIN, self.speed + delta)), 2)
        if new_speed == self.speed:
            return
        self.original_pos = self._original_pos_from_buffer()
        self.speed = new_speed
        self._rebuild_at_position()

    def _change_pitch(self, delta):
        new_cents = min(PITCH_MAX, max(PITCH_MIN, self.cents + delta))
        if new_cents == self.cents:
            return
        self.original_pos = self._original_pos_from_buffer()
        self.cents = new_cents
        self._rebuild_at_position()

    def _change_mode(self):
        modes = ["solo", "mute", "mix"]
        idx = (modes.index(self.mode) + 1) % len(modes)
        self.mode = modes[idx]
        self.original_pos = self._original_pos_from_buffer()
        self.raw_audio = mix_stems(self.stems, self.mode, self.part)
        self._rebuild_at_position()

    def _seek(self, seconds):
        # Work in buffer positions; clamp to loop region if looping
        delta = int(seconds * self.sr / self.speed)
        new_pos = self.pos + delta

        if self.looping and self.loop_start_orig is not None and self.loop_end_orig is not None:
            lo = self._loop_start_buffer() or 0
            hi = self._loop_end_buffer()
            new_pos = max(lo, min(new_pos, hi - 1))
        else:
            new_pos = max(0, min(new_pos, len(self.audio) - 1))

        self.pos = new_pos

    def _set_loop_point(self):
        current = int(self._original_pos_from_buffer())
        if self.loop_start_orig is None or self.loop_end_orig is not None:
            # Starting fresh: clear old points, set start
            self.looping = False
            self.loop_start_orig = current
            self.loop_end_orig = None
        else:
            # Start is set, end is not: set end
            if current > self.loop_start_orig:
                self.loop_end_orig = current
            else:
                # End before start: treat as new start
                self.loop_start_orig = current
                self.loop_end_orig = None

    def _toggle_hold(self):
        if self.holding:
            self.holding = False
            self.hold_slice = None
            self.pos = int(self.hold_end_orig / self.speed)
        else:
            hold_orig_samples = int(HOLD_DURATION * self.sr)
            current_orig = int(self._original_pos_from_buffer())
            self.hold_start_orig = max(0, current_orig - hold_orig_samples)
            self.hold_end_orig = current_orig
            self._rebuild_hold_slice()
            if len(self.hold_slice) == 0:
                return
            self.holding = True

    def _rebuild_hold_slice(self):
        buf_start = int(self.hold_start_orig / self.speed)
        buf_end = int(self.hold_end_orig / self.speed)
        self.hold_slice = self.audio[buf_start:buf_end].copy()
        self.hold_pos = 0

    def _toggle_loop(self):
        if self.loop_start_orig is None or self.loop_end_orig is None:
            return
        self.looping = not self.looping
        if self.looping:
            loop_start = self._loop_start_buffer() or 0
            loop_end = self._loop_end_buffer()
            if self.pos >= loop_end or self.pos < loop_start:
                self.pos = loop_start

    def _handle_key(self, key):
        if key == " ":
            self.playing = not self.playing
        elif key.lower() == "q":
            self.quit = True
        elif key == "0":
            self.pos = 0
            self.original_pos = 0.0
            self.playing = True
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
        elif key.lower() == "h":
            self._toggle_hold()
        elif key == "[":
            self._set_loop_point()
        elif key.lower() == "l":
            self._toggle_loop()


def play_interactive(stems_dir, part, initial_mode="solo", initial_speed=0.5):
    player = Player(stems_dir, part, initial_mode, initial_speed)
    player.run()
