# Learn To Play It (ltpi)

A CLI tool that helps musicians learn parts from recorded songs by:

1. **Separating** a recording into individual instrument stems (vocals, drums, bass, other) using AI source separation
2. **Practicing** an isolated part slowed down, with optional pitch shifting and section looping, progressively speeding up as you learn it
3. **Playing along** with the full mix minus your instrument — like karaoke, but for any part

## Installation

```bash
pip install -e .
```

Requires Python 3.10+ and FFmpeg installed on your system.

## Usage

### Separate a song into stems (one-time)

```bash
ltpi separate song.mp3
```

Runs AI source separation (Demucs) to produce individual stems. This takes a few minutes on CPU but only needs to be done once per song. Stems are cached in a `stems/` directory.

### Practice a part

```bash
ltpi practice song.mp3 bass
```

Opens an interactive playback session with the bass part isolated, starting at 50% speed. Use keyboard controls to adjust:

| Key       | Action                              |
|-----------|-------------------------------------|
| `SPACE`   | Play / pause                        |
| `↑` / `↓` | Speed ±5% (range: 25%–150%)       |
| `+` / `-` | Pitch ±10 cents                    |
| `[` / `]` | Set loop start / end               |
| `L`       | Toggle loop on/off                  |
| `0`       | Reset to beginning                  |
| `S`       | Cycle mode: solo → mute → mix      |
| `Q`       | Quit                                |

**Modes** (cycled with `S`):
- **solo** — hear only the selected part
- **mute** — hear everything *except* the selected part (play-along)
- **mix** — hear the full original mix

### Play along

```bash
ltpi play-along song.mp3 bass
```

Shortcut that opens the same interactive session but starts in **mute** mode at **100% speed** — everything except your part, at full tempo.

### List available parts

```bash
ltpi parts song.mp3
```

Shows which stems are available after separation.

## How it works

- **Source separation**: [Demucs](https://github.com/adefossez/demucs) (Meta Research) splits audio into four stems: vocals, drums, bass, and other
- **Time-stretching**: [Rubber Band](https://breakfastquay.com/rubberband/) changes playback speed without affecting pitch
- **Pitch-shifting**: Rubber Band shifts pitch in cents without affecting speed
- **Playback**: [sounddevice](https://python-sounddevice.readthedocs.io/) provides low-latency audio output

## Stem cache

Separated stems are stored under `stems/<song-name>/` and reused across sessions. Re-running `separate` on an already-processed song is a no-op.

## Future directions

- Beat-aware loop snapping (snap `[` / `]` to bar boundaries)
- Waveform visualisation in the terminal
- MIDI / guitar tab transcription from isolated parts
- GUI frontend
