import json

import numpy as np
import soundfile as sf

from learntoplayit.player import NUDGE_SECONDS, Player
from learntoplayit.separate import STEM_NAMES


SR = 44100
CHANNELS = 2
DURATION = 2


def _write_stems(tmp_path, beats_data=None):
    stems_dir = tmp_path / "stems"
    stems_dir.mkdir()
    t = np.linspace(0, DURATION, SR * DURATION, endpoint=False)
    audio = np.column_stack([
        0.3 * np.sin(2 * np.pi * 440 * t),
        0.3 * np.sin(2 * np.pi * 554 * t),
    ]).astype(np.float32)

    for name in STEM_NAMES:
        sf.write(str(stems_dir / f"{name}.wav"), audio, SR)

    if beats_data is not None:
        analysis_dir = stems_dir / "analysis"
        analysis_dir.mkdir()
        with open(analysis_dir / "beats.json", "w") as f:
            json.dump(beats_data, f)

    return stems_dir


def test_waveform_beats_empty_without_analysis(tmp_path):
    stems_dir = _write_stems(tmp_path)
    player = Player(str(stems_dir), "vocals", initial_speed=1.0)

    wd = player.waveform_bins(20)

    assert wd.beat_cols == []
    assert wd.downbeat_cols == []


def test_waveform_beats_are_viewport_columns(tmp_path):
    beats_data = {
        "beats": [0.5, 0.625],
        "downbeats": [0.5],
        "summary": {"bpm": 120.0, "time_signature": "4/4"},
    }
    stems_dir = _write_stems(tmp_path, beats_data)
    player = Player(str(stems_dir), "vocals", initial_speed=1.0)
    player.pos_orig = int(0.5 * SR)

    wd = player.waveform_bins(20)

    assert wd.downbeat_cols == [10.0]
    assert wd.beat_cols == [0.625 / NUDGE_SECONDS]
