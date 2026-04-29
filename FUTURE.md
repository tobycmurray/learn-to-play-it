# Future Design: Seamless Audio Rebuilds

This document is a design reference for eliminating audio pauses during speed/pitch/mode changes. It is **not currently planned for implementation** — the 2-3 second pause is acceptable for a CLI practice tool. This design would become relevant for a polished mobile/desktop app where perceived latency affects user retention.

## Goal

Eliminate audio pauses during speed/pitch/mode changes. Currently playback goes silent for 2-3 seconds while the audio buffer is rebuilt.

There are two approaches we might use, described below.

## Approach 1: Ring-buffer with pylibrb (recommended)

Replace pyrubberband (subprocess) with [pylibrb](https://github.com/pawel-glomski/pylibrb) — a direct Python binding to librubberband's real-time streaming API. This eliminates the batch-processing model entirely.

**Key properties:**
- No pre-processing. Audio is stretched/shifted on the fly, block by block.
- Speed/pitch changes are instant. Set `stretcher.time_ratio` / `stretcher.pitch_scale` — takes effect on the next block.
- No rebuild concept. `_pause_rebuild_resume` disappears entirely.
- Memory drops. No full processed buffer in memory — just raw stems + a small ring buffer (~16k samples).

**License:** pylibrb is GPLv2 (wraps librubberband which is GPL). We relicense from MIT to GPLv2.

### Architecture

```
┌──────────┐     ┌───────────┐     ┌─────────────┐     ┌──────────────┐
│ Raw mix  │ ──▶ │  Feeder   │ ──▶ │ Ring buffer │ ──▶ │   Callback   │ ──▶ speakers
│ (stems)  │     │  thread   │     │ (~16k samp) │     │ (sounddevice)│
└──────────┘     └───────────┘     └─────────────┘     └──────────────┘
                       │
                 ┌─────┴──────┐
                 │ Stretcher  │
                 │ (pylibrb)  │
                 └────────────┘
```

**Three threads:**
1. **Main thread** — handles keyboard input, updates parameters
2. **Feeder thread** — reads from raw mix, pushes through stretcher, writes to ring buffer
3. **Callback thread** (sounddevice) — reads from ring buffer, outputs to speakers

### pylibrb usage

```python
from pylibrb import RubberBandStretcher, Option

stretcher = RubberBandStretcher(
    sample_rate=44100,
    channels=2,
    options=Option.PROCESS_REALTIME | Option.ENGINE_FINER | Option.PITCH_HIGH_CONSISTENCY,
    initial_time_ratio=1 / speed,       # time_ratio = 1/speed (0.5x speed → ratio 2.0)
    initial_pitch_scale=2 ** (cents / 1200),  # cents to frequency ratio
)
stretcher.set_max_process_size(BLOCK_SIZE)

# In feeder loop:
stretcher.time_ratio = 1 / self.speed
stretcher.pitch_scale = 2 ** (self.cents / 1200)
stretcher.process(block)                # shape (channels, samples), float32
output = stretcher.retrieve_available() # variable-size output
ring_buffer.write(output)
```

### Ring buffer

Single-producer (feeder), single-consumer (callback). Lock-free via read/write indices:

```python
class RingBuffer:
    def __init__(self, capacity, channels):
        self.buf = np.zeros((capacity, channels), dtype=np.float32)
        self.capacity = capacity
        self.write_pos = 0
        self.read_pos = 0

    def available(self) -> int:
        return (self.write_pos - self.read_pos) % self.capacity

    def free(self) -> int:
        return self.capacity - 1 - self.available()

    def write(self, data): ...   # copy into buf, advance write_pos
    def read(self, n): ...       # copy from buf, advance read_pos
    def flush(self):             # reset both pointers (on seek)
        self.read_pos = self.write_pos
```

Size: ~16384 samples (~370ms at 44.1kHz). Enough to survive scheduling jitter without underrun, small enough that seek/parameter changes feel responsive.

### Position tracking

Position advances in the **feeder thread** as it reads from the raw mix:

```python
self.pos_orig += block_size  # feeder advances after each block read
```

The main thread reads `self.pos_orig` for the status display. Seeks write to `self.pos_orig` and signal the feeder to jump.

Note: there's a slight display-vs-audio discrepancy (~370ms) because the ring buffer holds audio that hasn't been output yet. This is cosmetic and not worth correcting.

### Feature mapping

#### Speed/pitch change
Main thread sets `self.speed` / `self.cents`. Feeder reads these each iteration and updates the stretcher properties. Change takes effect within one block (~46ms). No pause, no rebuild, no buffer swap.

#### Mode change (solo/mute/mix)
Mode change requires switching the raw audio source. The feeder checks `self.mode` each iteration and calls `mix_stems()` to produce the appropriate mix. Since `mix_stems` operates on the full stems array, we pre-compute all three mixes at startup and the feeder just switches which one it reads from:

```python
self.mixes = {
    "solo": mix_stems(stems, "solo", part),
    "mute": mix_stems(stems, "mute", part),
    "mix":  mix_stems(stems, "mix", part),
}
```

Mode switch is instant — the feeder reads from a different array on the next iteration.

#### Seek (Z/V/X/C/0)
1. Main thread sets `self.pos_orig` to new position
2. Main thread sets `self._seek_requested = True`
3. Feeder notices the flag, flushes the ring buffer, resets the stretcher, starts reading from new position
4. Brief silence (~one callback block) while ring buffer refills

#### Loop
Feeder handles wrapping: when `pos_orig` reaches `loop.end_orig`, jump back to `loop.start_orig`. The stretcher handles the input discontinuity gracefully in real-time mode (it's designed for live input).

#### Hold
When hold activates:
1. Capture the last HOLD_DURATION seconds of output from the ring buffer (read backwards from write_pos)
2. Store as `hold.slice`
3. Callback loops the hold slice instead of reading from ring buffer
4. Feeder pauses (stops advancing position)

When hold releases:
5. Callback resumes reading from ring buffer
6. Feeder resumes from where it was

Speed/pitch changes during hold: re-process the held region through a fresh stretcher with new parameters. This is a tiny slice (~0.2s) so it's instant.

### Implementation steps

- [ ] 1. Add `pylibrb` to dependencies, remove `pyrubberband`. Change license to GPLv2.
- [ ] 2. Implement `RingBuffer` class (single-producer, single-consumer, numpy-backed).
- [ ] 3. Implement feeder thread: reads from raw mix, feeds stretcher, writes to ring buffer. Handles seek/loop/pause signals.
- [ ] 4. Rewrite `Player.__init__`: pre-compute mixes, create stretcher, start feeder thread.
- [ ] 5. Rewrite `_callback`: read from ring buffer (or loop hold slice). Remove all buffer-position math.
- [ ] 6. Rewrite `_change_speed` / `_change_pitch`: just update `self.speed` / `self.cents`. No rebuild.
- [ ] 7. Rewrite `_change_mode`: just update `self.mode`. Feeder picks it up.
- [ ] 8. Rewrite `_seek`: set new pos_orig, signal feeder to flush and jump.
- [ ] 9. Rewrite `_toggle_hold`: capture slice from ring buffer, pause/resume feeder.
- [ ] 10. Update `audio.py`: remove `process_audio`, `time_stretch`, `pitch_shift` (no longer needed). Keep `load_all_stems` and `mix_stems`.
- [ ] 11. Update tests: remove pyrubberband-based audio processing tests, add ring buffer unit tests and stretcher integration tests.
- [ ] 12. Clean shutdown: signal feeder thread to exit, join it, close stream.

### What simplifies vs current code

| Current | After |
|---------|-------|
| `_pause_rebuild_resume` (pause, stretch entire song, resume) | Gone |
| `_buf_pos()` / `_orig_pos()` conversion math | Gone |
| `self.audio` (full processed buffer, ~20MB) | Gone |
| `process_audio()` / `time_stretch()` / `pitch_shift()` | Gone |
| Complex callback with buffer-position arithmetic | Simple ring buffer read |

### What stays the same

- `LoopRegion` dataclass and its invariant logic
- `HoldState` dataclass (slice capture mechanism changes, concept unchanged)
- Key handling (`_handle_key` dispatch)
- Status line display (reads pos_orig, speed, cents, mode — all unchanged)
- CLI layer (no changes)
- Separation (demucs, stems, caching — all unchanged)


## Approach 2: Double buffering

This keeps pyrubberband, but adds significant complexity over the librubberband and ringbuffer approach described above.

With double-buffering, the old buffer keeps playing until the new one is ready, then we swap atomically. With chunked processing on top, the change is perceived as near-instant (~60ms).

### Design

#### AudioState dataclass

Bundle the buffer and its processing parameters into a single immutable unit:

```python
@dataclass
class AudioState:
    audio: np.ndarray
    speed: float
    cents: float
    mode: str
```

The callback reads `state = self.state` once per invocation and uses that snapshot for all its work. This guarantees consistency — speed and buffer always match.

#### Atomic swap

Swapping `self.state = new_state` is a single pointer assignment, atomic under the GIL. No locks needed. The callback will pick up the new state on its next invocation (within one block of ~2048 samples / ~46ms at 44.1kHz).

#### Background rebuild

When the user changes speed/pitch/mode:

1. Record the "target" in `self._target = (speed, cents, mode)`
2. Increment `self._rebuild_version += 1`
3. Spawn a thread (or reuse a single-worker executor) to run `_do_rebuild(version, speed, cents, mode)`
4. The thread computes `mix_stems(...)` + `process_audio(...)`, producing a new `AudioState`
5. On completion, check `version == self._rebuild_version` — if not, discard (a newer request superseded this one)
6. If still current: `self.state = new_state`, rebuild hold slice if active

#### Version counter (latest-wins)

Rapid keypresses (e.g. W W W in quick succession) each bump the version and spawn a rebuild. Only the last one's result is applied — earlier threads check the version on completion and silently discard their work. This avoids queuing stale rebuilds or needing cancellation logic.

#### Position continuity

Position is tracked in `pos_orig` (original-song samples). The callback derives buffer index via:

```python
buf_pos = int(self.pos_orig / state.speed)
```

After a swap, `state.speed` changes, so `buf_pos` automatically maps to the correct location in the new (differently-stretched) buffer. No position adjustment needed.

#### Hold interaction

If hold is active when a swap lands, re-extract the hold slice from the new buffer:

```python
buf_start = int(hold.start_orig / new_state.speed)
buf_end = int(hold.end_orig / new_state.speed)
hold.slice = new_state.audio[buf_start:buf_end].copy()
hold.pos = 0
```

This is done as part of the swap, not in the background thread (it's cheap — just a slice copy).

#### Status line

During a rebuild, the status line shows the *target* speed/pitch/mode (what the user requested) with a rebuild indicator. This way the display is immediately responsive even though audio hasn't caught up yet:

```
  ▶ 1:23.45 / 4:12.00  |  speed: 60% ⟳  |  pitch: 0c  |  ...
```

The `⟳` (or similar) disappears once the swap lands.

### Double-buffer Implementation steps

- [ ] 1. Extract `AudioState` dataclass, update `__init__` to create initial state
- [ ] 2. Update `_callback` to read from `state = self.state` snapshot
- [ ] 3. Update `_buf_pos()` and `_buf_len()` to accept/use a state parameter
- [ ] 4. Replace `_pause_rebuild_resume` with `_request_rebuild` (spawns thread)
- [ ] 5. Add version counter and completion handler (swap + hold rebuild)
- [ ] 6. Update `_print_status` to show target params and rebuild indicator
- [ ] 7. Update `_change_speed`, `_change_pitch`, `_change_mode` to use new pattern
- [ ] 8. Ensure clean shutdown: wait for any in-flight rebuild thread before closing stream

### What doesn't change with the double-buffer approach (compared to now)

- Loop logic (operates in `pos_orig` space, unaffected)
- Seek/nudge (only touches `pos_orig`)
- Key handling (same keys, same entry points)
- Hold toggle (activation/deactivation logic unchanged)
- CLI layer (no changes)
- Tests (audio processing tests are independent of playback)

### Double-buffered Extension: Chunked processing for near-instant response

The double-buffer approach still has 2-3s of "old audio" playing while the new buffer builds. Chunked processing makes the change perceptible within ~60ms:

1. Divide the song into ~5-second chunks
2. On rebuild request, process the chunk at the playhead first (~60ms)
3. Snap that chunk into the new buffer immediately — user hears the change
4. Process remaining chunks outward from playhead in both directions
5. Each chunk snaps in as it completes; full buffer ready within ~3s

**Boundary handling:** rubberband maintains phase coherence across the signal. Independent chunks would produce discontinuities. Fix: process each chunk with ~0.5s overlap on each side, crossfade at boundaries. Adds ~10% overhead.

**Seek during rebuild:** if the user seeks into an unprocessed region, reprioritize that chunk. The playback falls back to the old buffer for that region until the new chunk is ready.

**Alternative — GPU acceleration:** torchaudio has `functional.time_stretch` and `pitch_shift` that run on GPU. Full-song processing drops to ~50ms. Downside: quality below rubberband (basic phase vocoder), not universal (requires CUDA). Could be offered as an optional fast path.
