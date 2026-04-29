# Learn To Play It (ltpi)

A CLI tool that helps musicians learn parts from recorded songs by:

1. **Separating** a recording into individual instrument stems (vocals, drums, bass, other) using AI source separation
2. **Practicing** an isolated part slowed down, with optional pitch shifting and section looping, progressively speeding up as you learn it
3. **Playing along** with the full mix minus your instrument — like karaoke, but for any part

## Prerequisites

- Python 3.10+
- FFmpeg (`brew install ffmpeg` on macOS, `apt install ffmpeg` on Debian/Ubuntu)
- Rubber Band CLI (`brew install rubberband` on macOS, `apt install rubberband-cli` on Debian/Ubuntu)

## Installation

```bash
git clone https://github.com/tobycmurray/learn-to-play-it.git
cd learn-to-play-it
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `ltpi` command into your virtualenv. Activate the venv (`source .venv/bin/activate`) before each session.

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

| Key     | Action                                |
|---------|---------------------------------------|
| `SPACE` | Play / pause                          |
| `W`/`S` | Speed up / down ±10% (range: 20%–150%) |
| `E`/`D` | Pitch up / down ±10 cents (range: ±200c) |
| `Z`/`V` | Seek back / forward 5 seconds        |
| `X`/`C` | Nudge back / forward 0.05 seconds    |
| `[`/`]` | Set loop start / end                  |
| `L`     | Toggle loop on/off                    |
| `H`     | Hold — freeze last 200ms and loop it |
| `M`     | Cycle mode: solo → mute → mix        |
| `0`     | Restart (or loop start if looping)    |
| `Q`     | Quit                                  |

**Modes** (cycled with `M`):
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

- **Source separation**: [Demucs](https://github.com/adefossez/demucs) (Meta Research) splits audio into six stems: vocals, drums, bass, guitar, piano, and other
- **Time-stretching**: [Rubber Band](https://breakfastquay.com/rubberband/) changes playback speed without affecting pitch
- **Pitch-shifting**: Rubber Band shifts pitch in cents without affecting speed
- **Playback**: [sounddevice](https://python-sounddevice.readthedocs.io/) provides low-latency audio output

## Stem cache

Separated stems are stored under `stems/<song-name>/` and reused across sessions. Re-running `separate` on an already-processed song is a no-op.

## Getting audio from YouTube

You can use [yt-dlp](https://github.com/yt-dlp/yt-dlp) to download audio from YouTube for use with ltpi:

```bash
# Install yt-dlp
brew install yt-dlp        # macOS
pip install yt-dlp         # or via pip

# Download audio as MP3
yt-dlp -x --audio-format mp3 -o "song.%(ext)s" "https://youtube.com/watch?v=..."

# Then separate and practice
ltpi separate song.mp3
ltpi practice song.mp3 guitar
```

**Legal note**: Downloading audio from YouTube may violate YouTube's Terms of Service and could raise copyright concerns depending on your jurisdiction. Users are responsible for ensuring their use complies with applicable laws and terms. This tool is intended for personal practice and educational use.

## Future directions

- Beat-aware loop snapping (snap `[` / `]` to bar boundaries)
- Waveform visualisation in the terminal
- MIDI / guitar tab transcription from isolated parts
- GUI frontend
