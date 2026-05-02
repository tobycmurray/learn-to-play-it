import json
from pathlib import Path

import numpy as np

from .separate import get_stems_dir

CLICK_VOLUME = 0.4
DOWNBEAT_FREQ = 1500.0
BEAT_FREQ = 1000.0
CLICK_DURATION = 0.02


def _analysis_dir(audio_file: str) -> Path:
    return get_stems_dir(audio_file) / "analysis"


def beats_exist(audio_file: str) -> bool:
    return (_analysis_dir(audio_file) / "beats.json").exists()


def load_beats(audio_file: str) -> dict:
    path = _analysis_dir(audio_file) / "beats.json"
    with open(path) as f:
        return json.load(f)


def load_beats_from_dir(stems_dir: Path) -> dict | None:
    path = stems_dir / "analysis" / "beats.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def render_click_track(beats_data: dict, song_len: int, sr: int, channels: int) -> np.ndarray:
    """Render a click track as a numpy array matching song dimensions."""
    click_samples = int(CLICK_DURATION * sr)
    t = np.arange(click_samples) / sr
    envelope = np.exp(-t * 40)

    downbeat_click = (np.sin(2 * np.pi * DOWNBEAT_FREQ * t) * envelope * CLICK_VOLUME).astype(np.float32)
    beat_click = (np.sin(2 * np.pi * BEAT_FREQ * t) * envelope * CLICK_VOLUME).astype(np.float32)

    downbeat_samples = {int(db * sr) for db in beats_data["downbeats"]}
    track = np.zeros((song_len, channels), dtype=np.float32)

    for beat_time in beats_data["beats"]:
        sample_pos = int(beat_time * sr)
        if sample_pos + click_samples > song_len:
            break
        click = downbeat_click if sample_pos in downbeat_samples else beat_click
        for ch in range(channels):
            track[sample_pos:sample_pos + click_samples, ch] += click

    return track


def ensure_beats(audio_file: str) -> dict:
    if beats_exist(audio_file):
        return load_beats(audio_file)
    return detect_beats(audio_file)


def detect_beats(audio_file: str, from_stem: str | None = None) -> dict:
    from beat_this.inference import File2Beats

    if from_stem is not None:
        stems_dir = get_stems_dir(audio_file)
        input_path = str(stems_dir / f"{from_stem}.wav")
    else:
        input_path = audio_file

    model = File2Beats(checkpoint_path="final0", device="cpu")
    beat_times, downbeat_times = model(input_path)

    beats = beat_times.tolist()
    downbeats = downbeat_times.tolist()

    ibi = np.diff(beat_times)
    bpm = float(60.0 / np.median(ibi)) if len(ibi) > 0 else 0.0

    if len(downbeats) >= 2:
        beats_arr = np.array(beats)
        counts = []
        for i in range(len(downbeats) - 1):
            n = np.sum((beats_arr >= downbeats[i]) & (beats_arr < downbeats[i + 1]))
            counts.append(int(n))
        beats_per_bar = int(np.median(counts)) if counts else 4
    else:
        beats_per_bar = 4

    result = {
        "beats": beats,
        "downbeats": downbeats,
        "summary": {
            "bpm": round(bpm, 1),
            "time_signature": f"{beats_per_bar}/4",
        },
    }

    out_dir = _analysis_dir(audio_file)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "beats.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
