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

- [x] 3.1 Implement `audio.py` — load stems with soundfile, return numpy arrays and sample rate
- [x] 3.2 Add time-stretching (change speed without changing pitch) using pyrubberband
- [x] 3.3 Add pitch-shifting (change pitch in cents without changing speed) using pyrubberband
- [x] 3.4 Add stem mixing: combine selected stems into a single output (for solo/mute/mix modes)

## Phase 4: Interactive playback

- [x] 4.1 Implement basic `player.py` — play a numpy audio array through sounddevice with play/pause and position tracking
- [x] 4.2 Add real-time speed control (re-stretch on speed change)
- [x] 4.3 Add real-time pitch control (re-shift on pitch change)
- [x] 4.4 Add mode cycling (solo / mute / mix) — re-mix stems on mode change
- [x] 4.5 Add loop points: `[` to set start/end, `L` to toggle, playback wraps within loop
- [x] 4.6 Add seek (`A`/`D` ±5s, `0` restart), hold (`H` freezes last 100ms)
- [x] 4.7 Add terminal UI: show current position, speed, pitch, mode, loop status

## Phase 5: CLI integration

- [x] 5.1 Wire up `ltpi practice <file> <part>` — auto-separate if needed, then enter interactive playback in solo mode at 50% speed
- [x] 5.2 Wire up `ltpi play-along <file> <part>` — same but mute mode at 100% speed
- [x] 5.3 End-to-end manual test of full workflow

## Dependencies

| Package       | Purpose                                  |
|---------------|------------------------------------------|
| demucs        | AI source separation                     |
| pyrubberband  | Time-stretching and pitch-shifting       |
| soundfile     | Read/write audio files                   |
| sounddevice   | Low-latency audio playback               |
| numpy         | Audio data as arrays                     |
| click         | CLI framework                            |

## Phase 6: Polish and usability

- [x] 6.1 Hash-based file identification: map audio files to SHA-256 hash of contents, store stems in `stems/<hash>/`. This means renaming or moving the mp3 won't cause re-separation, and two copies of the same file share stems.
- [x] 6.2 Add `--speed` and `--pitch` options to `practice` and `play-along` commands to set initial speed (as percentage, e.g. `--speed 70`) and pitch (in cents, e.g. `--pitch -50`). Defaults unchanged (practice: 50% speed, 0c; play-along: 100% speed, 0c).
- [x] 6.3 Add `ltpi clean <file>` command: resolve file to hash, find and delete corresponding stems directory. Print what was deleted or say nothing to clean.
- [x] 6.4 Show total duration in MM:SS format in the status line (in addition to seconds) for longer tracks where raw seconds are hard to interpret.
- [x] 6.5 Add `--stems-dir` global option to override the default `stems/` location (e.g. store stems on an external drive or shared location).
- [x] 6.6 Handle edge cases: missing FFmpeg/rubberband CLI (friendly error on launch), --speed/--pitch input validation.

## Notes

- Phases 1–5 are sequential: each depends on the previous
- Phase 6 tasks are independent of each other and can be done in any order
- Phase 4 is the most complex — the interactive player with real-time controls
- We will test with real audio at the end of each phase where applicable
