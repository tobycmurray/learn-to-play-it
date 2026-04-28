import sys
import tty
import termios

import numpy as np
import sounddevice as sd

from .audio import load_all_stems, mix_stems, process_audio

SPEED_MIN = 0.25
SPEED_MAX = 1.5
SPEED_STEP = 0.05
PITCH_STEP = 10
PITCH_MIN = -200
PITCH_MAX = 200


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

    def _rebuild_audio(self):
        self.audio = process_audio(self.raw_audio, self.sr, self.speed, self.cents)

    def _original_pos_from_buffer(self):
        return self.pos * self.speed

    def _buffer_pos_from_original(self):
        return int(self.original_pos / self.speed)

    def _callback(self, outdata, frames, time_info, status):
        if not self.playing:
            outdata[:] = 0
            return

        end = self.pos + frames
        if end <= len(self.audio):
            outdata[:] = self.audio[self.pos:end]
        else:
            valid = len(self.audio) - self.pos
            outdata[:valid] = self.audio[self.pos:self.pos + valid]
            outdata[valid:] = 0
            self.playing = False
        self.pos = min(end, len(self.audio))

    def _print_status(self):
        original_secs = self._original_pos_from_buffer() / self.sr
        total_secs = len(self.raw_audio) / self.sr
        state = "▶" if self.playing else "⏸"
        speed_pct = int(round(self.speed * 100))
        cents_str = f"{self.cents:+.0f}" if self.cents != 0 else "0"
        print(
            f"\r  {state} {original_secs:5.1f}s / {total_secs:.1f}s  |  "
            f"speed: {speed_pct}%  |  pitch: {cents_str}c  |  "
            f"mode: {self.mode}  |  part: {self.part}     ",
            end="", flush=True,
        )

    def run(self):
        print(f"Playing: {self.part} ({self.mode})")
        print("Controls: SPACE=play/pause  W/X=speed  E/C=pitch  S=cycle mode  0=restart  Q=quit")
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
        self.original_pos = self._original_pos_from_buffer()
        self._rebuild_audio()
        self.pos = min(self._buffer_pos_from_original(), max(0, len(self.audio) - 1))
        self.playing = was_playing

    def _change_speed(self, delta):
        new_speed = round(min(SPEED_MAX, max(SPEED_MIN, self.speed + delta)), 2)
        if new_speed == self.speed:
            return
        self.speed = new_speed
        self._rebuild_at_position()

    def _change_pitch(self, delta):
        new_cents = min(PITCH_MAX, max(PITCH_MIN, self.cents + delta))
        if new_cents == self.cents:
            return
        self.cents = new_cents
        self._rebuild_at_position()

    def _change_mode(self):
        modes = ["solo", "mute", "mix"]
        idx = (modes.index(self.mode) + 1) % len(modes)
        self.mode = modes[idx]
        self.raw_audio = mix_stems(self.stems, self.mode, self.part)
        self._rebuild_at_position()

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


def play_interactive(stems_dir, part, initial_mode="solo", initial_speed=0.5):
    player = Player(stems_dir, part, initial_mode, initial_speed)
    player.run()
