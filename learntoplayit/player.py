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
PITCH_MIN = -1200
PITCH_MAX = 1200
SEEK_SECONDS = 5
NUDGE_SECONDS = 0.05
HOLD_DURATION = 0.4

BLOCK_SIZE = 1024
RING_CAPACITY = 16384
MODES = ["solo", "backing", "mix"]


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

    def active_bounds(self) -> tuple[int, int] | None:
        """Returns (start_orig, end_orig) if active, else None.

        When active, both bounds are guaranteed non-None by _enforce().
        """
        if self.active:
            return self.start_orig, self.end_orig
        return None


@dataclass
class HoldState:
    start_orig: int
    end_orig: int
    raw: np.ndarray
    slice: np.ndarray
    pos: int = 0


@dataclass
class WaveformData:
    bins: np.ndarray
    # Column positions are fractional (sub-bin precision) so the GUI can render
    # the playhead and loop markers at their exact location within a bin
    # rather than snapped to bin boundaries. The TUI rounds to int.
    cursor_col: float
    loop_start_col: float | None
    loop_end_col: float | None
    loop_active: bool


class Player:
    """Audio engine with real-time speed/pitch/loop/hold controls.

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
            "backing": mix_stems(self.stems, "mute", part),
            "mix": mix_stems(self.stems, "mix", part),
        }
        self.channels = self.mixes["solo"].shape[1] if self.mixes["solo"].ndim > 1 else 1
        self.song_len = len(self.mixes["solo"])

        self._click_track, self._count_in_track, self._count_in_start = self._load_beats(stems_dir)

        self.click_active = self._click_track is not None
        self.count_in_enabled = self._count_in_track is not None
        self._mix_peaks = {mode: self._compute_rms_peak(mix) for mode, mix in self.mixes.items()}

        self.ring = RingBuffer(RING_CAPACITY, self.channels)
        self.stretcher = self._make_stretcher()

        self.pos_orig = 0
        self.device = device
        self.playing = False
        self.quit = False
        self._stream = None

        self.loop: LoopRegion | None = None
        self.hold: HoldState | None = None

        self._seek_requested = False
        self._feeder_stop = threading.Event()
        self._feeder_paused = False
        self._feeder_thread = None

    def _load_beats(self, stems_dir):
        from pathlib import Path
        from .beats import load_beats_from_dir, render_click_track, compute_count_in

        beats_data = load_beats_from_dir(Path(stems_dir))
        if beats_data is None:
            return None, None, 0

        click_track = render_click_track(beats_data, self.song_len, self.sr, self.channels)

        ci_result = compute_count_in(beats_data, self.sr, self.channels)
        if ci_result is None:
            return click_track, None, 0
        return click_track, ci_result[0], ci_result[1]

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
    def playback_position(self):
        """Current playback position in seconds."""
        return self._playback_pos / self.sr

    @property
    def song_duration(self):
        """Total song duration in seconds."""
        return self.song_len / self.sr

    @property
    def loop_active(self):
        loop = self.loop
        return loop is not None and loop.active

    @property
    def loop_bounds(self):
        """Loop info: (start_secs|None, end_secs|None, active), or None if no loop."""
        loop = self.loop
        if loop is None:
            return None
        start = loop.start_orig / self.sr if loop.start_orig is not None else None
        end = loop.end_orig / self.sr if loop.end_orig is not None else None
        return start, end, loop.active

    @property
    def _playback_pos(self):
        buffered_orig = int(self.ring.available() * self.speed)
        pos = max(0, self.pos_orig - buffered_orig)
        if self.loop_active:
            start, end = self.loop.active_bounds()
            loop_len = end - start
            if loop_len > 0:
                pos = start + (pos - start) % loop_len
        return pos

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

    def _read_block(self, pos, block_size):
        """Read a block of audio at pos, handling negative (count-in) territory."""
        mix = self.mixes[self.mode]

        if pos >= 0:
            block = mix[pos:pos + block_size].copy()
            if self.click_active and self._click_track is not None:
                block += self._click_track[pos:pos + block_size]
        elif pos + block_size <= 0:
            block = np.zeros((block_size, self.channels), dtype=np.float32)
        else:
            silent_part = -pos
            audio_part = block_size - silent_part
            block = np.zeros((block_size, self.channels), dtype=np.float32)
            block[silent_part:] = mix[0:audio_part]
            if self.click_active and self._click_track is not None:
                block[silent_part:] += self._click_track[0:audio_part]

        if self.count_in_enabled and self._count_in_track is not None:
            ci_idx = pos - self._count_in_start
            ci_end = min(ci_idx + block_size, len(self._count_in_track))
            if pos >= self._count_in_start and pos < self._count_in_start + len(self._count_in_track):
                block[0:(ci_end - ci_idx)] += self._count_in_track[ci_idx:ci_end]

        return block

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

            pos = self.pos_orig
            bounds = self.loop.active_bounds() if self.loop_active else None
            end_pos = bounds[1] if bounds else self.song_len

            if pos >= end_pos:
                if bounds:
                    self.pos_orig = bounds[0]
                    continue
                self._feeder_stop.wait(0.01)
                continue

            if self.ring.free() < BLOCK_SIZE * 4:
                self._feeder_stop.wait(0.005)
                continue

            block_size = min(BLOCK_SIZE, end_pos - pos)
            block = self._read_block(pos, block_size)
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

    # --- Waveform data ---

    def waveform_bins(self, num_bins):
        bin_samples = int(NUDGE_SECONDS * self.sr)
        half = num_bins // 2
        pos_snapped = (self._playback_pos // bin_samples) * bin_samples
        window_start = pos_snapped - half * bin_samples

        mix = self.mixes[self.mode]
        end = window_start + num_bins * bin_samples
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
            for i in range(num_bins)
        ])
        bins /= self._mix_peaks[self.mode]
        np.clip(bins, 0, 1, out=bins)

        # Sub-bin-precision cursor: bins are anchored at pos_snapped, so the
        # cursor moves smoothly through its bin as playback advances within it
        # then "shifts" back to the bin's left edge when crossing a boundary.
        cursor_col = (self._playback_pos - window_start) / bin_samples

        loop_start_col = None
        loop_end_col = None
        loop = self.loop
        if loop is not None:
            if loop.start_orig is not None:
                col = (loop.start_orig - window_start) / bin_samples
                if 0 <= col < num_bins:
                    loop_start_col = col
            if loop.end_orig is not None:
                col = (loop.end_orig - window_start) / bin_samples
                if 0 <= col < num_bins:
                    loop_end_col = col

        return WaveformData(bins=bins, cursor_col=cursor_col, loop_start_col=loop_start_col, loop_end_col=loop_end_col, loop_active=self.loop_active)

    # --- Commands ---

    def toggle_play(self):
        self.playing = not self.playing

    def change_speed(self, delta):
        new_speed = round(min(SPEED_MAX, max(SPEED_MIN, self.speed + delta)), 2)
        if new_speed == self.speed:
            return
        self.speed = new_speed
        self._rebuild_hold_slice()

    def change_pitch(self, delta):
        new_cents = min(PITCH_MAX, max(PITCH_MIN, self.cents + delta))
        if new_cents == self.cents:
            return
        self.cents = new_cents
        self._rebuild_hold_slice()

    def set_mode(self, mode):
        if mode in MODES:
            self.mode = mode

    def toggle_click(self):
        if self._click_track is not None:
            self.click_active = not self.click_active

    def toggle_count_in(self):
        if self._count_in_track is not None:
            self.count_in_enabled = not self.count_in_enabled

    def seek(self, seconds):
        if self.hold is not None:
            return
        delta_orig = int(seconds * self.sr)
        new_pos = self._playback_pos + delta_orig

        bounds = self.loop.active_bounds() if self.loop_active else None
        if bounds:
            new_pos = max(bounds[0], min(new_pos, bounds[1] - 1))
        else:
            new_pos = max(0, min(new_pos, self.song_len - 1))

        self.pos_orig = new_pos
        self._seek_requested = True

    def set_loop_start(self):
        if self.loop is None:
            self.loop = LoopRegion()
        self.loop.set_start(self._playback_pos)

    def set_loop_end(self):
        if self.loop is None:
            self.loop = LoopRegion()
        self.loop.set_end(self._playback_pos)

    def toggle_loop(self):
        loop = self.loop
        if loop is None or not loop.is_complete():
            return
        loop.active = not loop.active
        if loop.active:
            if self._playback_pos >= loop.end_orig or self._playback_pos < loop.start_orig:
                self.pos_orig = loop.start_orig
                self._seek_requested = True

    def toggle_hold(self):
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

    @property
    def _start_pos(self):
        if self.count_in_enabled and self._count_in_start < 0:
            return self._count_in_start
        return 0

    def restart(self):
        if self.hold is not None:
            return
        bounds = self.loop.active_bounds() if self.loop_active else None
        self.pos_orig = bounds[0] if bounds else self._start_pos
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

    # --- Lifecycle ---

    def start(self):
        self.pos_orig = self._start_pos
        self._stream = sd.OutputStream(
            samplerate=self.sr,
            channels=self.channels,
            callback=self._callback,
            blocksize=2048,
            device=self.device,
        )
        self._stream.start()
        self._feeder_thread = threading.Thread(target=self._feeder_loop, daemon=True)
        self._feeder_thread.start()
        self.playing = True

    def stop(self):
        self._feeder_stop.set()
        if self._feeder_thread is not None:
            self._feeder_thread.join(timeout=2)
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
