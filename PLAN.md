# Implementation Plan

## Phase 1: Project scaffolding

- [x] 1.1 Create `pyproject.toml` with dependencies (demucs, pyrubberband, soundfile, sounddevice, numpy, click)
- [x] 1.2 Create package structure: `learntoplayit/` with `__init__.py`, `cli.py`, `separate.py`, `audio.py`, `player.py`
- [x] 1.3 Wire up the `ltpi` CLI entry point using Click with subcommands (`separate`, `parts`, `practice`, `play-along`)
- [x] 1.4 Add `.gitignore` (stems/, __pycache__/, *.egg-info, etc.)

## Phase 2: Source separation

- [x] 2.1 Implement `separate.py` — wrapper around Demucs that takes an audio file path and produces stems in `stems/<song-name>/`
- [x] 2.2 Add stem caching: skip separation if stems already exist for a given song
- [x] 2.3 Wire up `ltpi separate <file>` command
- [x] 2.4 Wire up `ltpi parts <file>` command (list available stems)
- [x] 2.5 Test with a real audio file end-to-end

## Phase 3: Audio processing

- [ ] 3.1 Implement `audio.py` — load stems with soundfile, return numpy arrays and sample rate
- [ ] 3.2 Add time-stretching (change speed without changing pitch) using pyrubberband
- [ ] 3.3 Add pitch-shifting (change pitch in cents without changing speed) using pyrubberband
- [ ] 3.4 Add stem mixing: combine selected stems into a single output (for solo/mute/mix modes)

## Phase 4: Interactive playback

- [ ] 4.1 Implement basic `player.py` — play a numpy audio array through sounddevice with play/pause and position tracking
- [ ] 4.2 Add real-time speed control (re-stretch on speed change)
- [ ] 4.3 Add real-time pitch control (re-shift on pitch change)
- [ ] 4.4 Add mode cycling (solo / mute / mix) — re-mix stems on mode change
- [ ] 4.5 Add loop points: `[` / `]` to set, `L` to toggle, playback wraps within loop
- [ ] 4.6 Add seek-to-start (`0` key)
- [ ] 4.7 Add terminal UI: show current position, speed, pitch, mode, loop status

## Phase 5: CLI integration

- [ ] 5.1 Wire up `ltpi practice <file> <part>` — auto-separate if needed, then enter interactive playback in solo mode at 50% speed
- [ ] 5.2 Wire up `ltpi play-along <file> <part>` — same but mute mode at 100% speed
- [ ] 5.3 Handle edge cases: missing file, invalid part name, missing FFmpeg, etc.
- [ ] 5.4 End-to-end manual test of full workflow

## Dependencies

| Package       | Purpose                                  |
|---------------|------------------------------------------|
| demucs        | AI source separation                     |
| pyrubberband  | Time-stretching and pitch-shifting       |
| soundfile     | Read/write audio files                   |
| sounddevice   | Low-latency audio playback               |
| numpy         | Audio data as arrays                     |
| click         | CLI framework                            |

## Notes

- Phases are sequential: each depends on the previous
- Within a phase, tasks can mostly be done in order, though some are parallelisable
- Phase 4 is the most complex — the interactive player with real-time controls
- We will test with real audio at the end of each phase where applicable
