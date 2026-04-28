import sys
import tty
import termios
import threading

import numpy as np
import sounddevice as sd

from .audio import load_all_stems, mix_stems


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

        self.audio = mix_stems(self.stems, self.mode, self.part)
        self.pos = 0
        self.playing = False
        self.quit = False
        self.stream = None

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
        pos_secs = self.pos / self.sr
        total_secs = len(self.audio) / self.sr
        state = "▶" if self.playing else "⏸"
        print(
            f"\r  {state} {pos_secs:5.1f}s / {total_secs:.1f}s  |  "
            f"mode: {self.mode}  |  part: {self.part}     ",
            end="", flush=True,
        )

    def run(self):
        print(f"Playing: {self.part} ({self.mode})")
        print("Controls: SPACE=play/pause  S=cycle mode  0=restart  Q=quit")
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
                self._handle_key(key)
        finally:
            self.stream.stop()
            self.stream.close()
            print()

    def _handle_key(self, key):
        if key == " ":
            self.playing = not self.playing
        elif key.lower() == "q":
            self.quit = True
        elif key == "0":
            self.pos = 0
            self.playing = True
        elif key.lower() == "s":
            modes = ["solo", "mute", "mix"]
            idx = (modes.index(self.mode) + 1) % len(modes)
            self.mode = modes[idx]
            self.audio = mix_stems(self.stems, self.mode, self.part)
            if self.pos > len(self.audio):
                self.pos = 0


def play_interactive(stems_dir, part, initial_mode="solo", initial_speed=0.5):
    player = Player(stems_dir, part, initial_mode, initial_speed)
    player.run()
