import math
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


def _compute_listener_pos(pos_orig: int, buffered_orig: int,
                          loop_bounds: tuple[int, int] | None) -> int:
    """Translate the producer cursor into the position currently being heard.

    The feeder thread runs ahead of the audio callback, writing audio into a
    ring buffer. `pos_orig` is the producer-side cursor — the next source
    sample the feeder will read. The listener trails the producer by however
    much audio is currently buffered between them (`buffered_orig`, in
    source-sample units).

    For non-looping playback this is just `pos_orig - buffered_orig`. For
    looping playback the feeder periodically wraps `pos_orig` from `end` back
    to `start` while the ring buffer still holds audio for samples just
    before `end`. In that brief window `pos_orig - buffered_orig` is below
    `start`, and we wrap-forward to "near end" so the displayed position
    matches the audio actually being heard.

    The wrap is *only* applied when pos < start. Two cases that look similar
    but must NOT wrap:

      - pos == end exactly: arises when the user shrinks the loop to their
        current playhead via set_loop_end. We want the playhead to stay
        visually put (at end) rather than jump to start.

      - pos in [start, end): obviously no wrap needed; pos is already in range.
    """
    pos = max(0, pos_orig - buffered_orig)
    if loop_bounds is not None:
        start, end = loop_bounds
        loop_len = end - start
        if loop_len > 0 and pos < start:
            pos = start + (pos - start) % loop_len
    return pos


@dataclass
class WaveformData:
    """A snapshot of the waveform viewport.

    The whole song's amplitude envelope is precomputed as a fixed grid of
    NUDGE_SECONDS-wide bins. The viewport slides smoothly across that grid;
    `viewport_start_bin` is the fractional global bin index of the viewport's
    left edge.

    Coordinate systems used by callers:
      - global bin index: integer 0..total_bins. Indexes into the song's
        canonical bin grid. Fractional values represent positions between bins.
      - viewport column: float 0..num_bins. Position within the visible viewport.
        Equal to (global_bin - viewport_start_bin).
      - pixel x: 0..viewport_pixel_width. Screen position. Equal to
        (viewport_col * viewport_pixel_width / num_bins).

    `bins` has length num_bins + 1 so the renderer can show a partial bin at
    the right edge as the viewport offset changes. Use `num_bins` to discover
    the logical viewport width.
    """
    bins: np.ndarray
    viewport_start_bin: float
    loop_start_col: float | None
    loop_end_col: float | None
    loop_active: bool
    total_bins: int

    @property
    def num_bins(self) -> int:
        """Logical viewport width in bins (= len(bins) - 1)."""
        return len(self.bins) - 1

    @property
    def bin_offset(self) -> float:
        """How far through bins[0] the viewport's left edge sits, in [0, 1)."""
        return self.viewport_start_bin - math.floor(self.viewport_start_bin)

    @property
    def cursor_col(self) -> float:
        """Cursor's column position in the viewport — always the centre."""
        return self.num_bins / 2

    def x_to_global_bin(self, x_px: float, viewport_pixel_width: int) -> int:
        """Map a pixel x within the viewport to a global bin index."""
        bar_w = viewport_pixel_width / self.num_bins
        return math.floor(x_px / bar_w + self.viewport_start_bin)

    def global_bin_to_col(self, global_bin: float) -> float:
        """Map a global bin index to a (fractional) viewport column."""
        return global_bin - self.viewport_start_bin


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
        # Precompute the full normalized amplitude envelope per mode. This is
        # the canonical bin grid for the song; waveform_bins() just slices.
        self._all_bins = {mode: self._compute_normalized_bins(mix) for mode, mix in self.mixes.items()}

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

    def _compute_normalized_bins(self, mix):
        """Compute the full RMS-bin envelope for a mix and normalize to [0, 1]."""
        bin_samples = int(NUDGE_SECONDS * self.sr)
        mono = np.abs(mix).max(axis=1) if mix.ndim > 1 else np.abs(mix.ravel())
        n_bins = len(mono) // bin_samples
        if n_bins == 0:
            return np.zeros(0, dtype=np.float32)
        trimmed = mono[:n_bins * bin_samples].reshape(n_bins, bin_samples)
        bins = np.sqrt(np.mean(trimmed ** 2, axis=1)).astype(np.float32)
        peak = float(bins.max()) or 1.0
        bins /= peak
        np.clip(bins, 0, 1, out=bins)
        return bins

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
        loop_bounds = self.loop.active_bounds() if self.loop_active else None
        return _compute_listener_pos(self.pos_orig, buffered_orig, loop_bounds)

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
        all_bins = self._all_bins[self.mode]
        total_bins = len(all_bins)

        # Cursor sits at the fixed visual centre of the viewport; the viewport
        # slides smoothly across the song's canonical bin grid as playback advances.
        cursor_bin = self._playback_pos / bin_samples
        viewport_start_bin = cursor_bin - num_bins / 2
        start_int = math.floor(viewport_start_bin)

        # Slice (num_bins + 1) bins from the cache — one extra so the renderer
        # can show the partial bin at the right edge. Zero-pad where the
        # viewport extends outside the song.
        bins = np.zeros(num_bins + 1, dtype=np.float32)
        src_start = max(0, start_int)
        src_end = min(total_bins, start_int + num_bins + 1)
        if src_end > src_start:
            dst_start = src_start - start_int
            bins[dst_start:dst_start + (src_end - src_start)] = all_bins[src_start:src_end]

        loop_start_col = None
        loop_end_col = None
        loop = self.loop
        if loop is not None:
            if loop.start_orig is not None:
                col = loop.start_orig / bin_samples - viewport_start_bin
                if 0 <= col < num_bins:
                    loop_start_col = col
            if loop.end_orig is not None:
                col = loop.end_orig / bin_samples - viewport_start_bin
                if 0 <= col < num_bins:
                    loop_end_col = col

        return WaveformData(
            bins=bins,
            viewport_start_bin=float(viewport_start_bin),
            loop_start_col=loop_start_col,
            loop_end_col=loop_end_col,
            loop_active=self.loop_active,
            total_bins=total_bins,
        )

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
        if not loop.active:
            # Turning loop on
            loop.active = True
            if self._playback_pos >= loop.end_orig or self._playback_pos < loop.start_orig:
                self.pos_orig = loop.start_orig
                self._seek_requested = True
        else:
            # Turning loop off. The _playback_pos wrap formula was reporting
            # the audio's actual position (compensating for buffered audio
            # generated before pos_orig wrapped). Once that compensation goes
            # away, we'd see pos_orig - buffered_orig directly, which can be
            # well before the displayed position. Snap pos_orig to the
            # displayed position and reset the feeder so the ring buffer
            # matches.
            current_pos = self._playback_pos
            loop.active = False
            self.pos_orig = current_pos
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
