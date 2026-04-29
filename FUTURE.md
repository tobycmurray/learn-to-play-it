# Future Design: Seamless Audio Rebuilds

This document is a design reference for eliminating audio pauses during speed/pitch/mode changes. It is **not currently planned for implementation** — the 2-3 second pause is acceptable for a CLI practice tool. This design would become relevant for a polished mobile/desktop app where perceived latency affects user retention.

## Goal

Eliminate audio pauses during speed/pitch/mode changes. Currently playback goes silent for 2-3 seconds while the audio buffer is rebuilt.

There are two approaches we might use, described below.

## Approach 1: Ring-buffer with librubberband

This approach requires using the librubberband C API via ctypes, ditching pyrubberband entirely.

librubberband has a real-time API designed for exactly our use case. Instead of processing the entire song upfront, you create a
"stretcher" instance with your desired speed/pitch, then feed it audio blocks and get processed blocks back with minimal latency.
This means:

- No pre-processing at all. The audio callback (or a feeder thread) reads from the raw stems and stretches on the fly.
- Speed/pitch changes are instant. Create a new stretcher with the new parameters. Next block comes out at the new speed. The
library handles phase coherence across the transition internally.
- No rebuild concept. No double-buffering, no chunking, no background threads. The entire _pause_rebuild_resume pattern
disappears.
- Memory drops. No need to store the full processed buffer — just the raw stems plus a small output ring buffer.

This is a fundamentally different architecture — streaming instead of batch — and it's simpler than what we have now, not more
complex. The double-buffered design below would be unnecessary here.

The implementation would roughly be:
1. Load librubberband via ctypes at startup
2. Create a stretcher instance with current speed/pitch
3. A feeder thread reads raw stem audio, pushes through the stretcher, fills a small ring buffer
4. The sounddevice callback reads from the ring buffer
5. On speed/pitch change: create a new stretcher, feeder picks it up immediately

This would require researching the exact librubberband API and seeing if there's an existing Python binding, or whether we'd
need a thin ctypes wrapper.


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
