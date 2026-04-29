import numpy as np
import soundfile as sf
import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def synthetic_wav(tmp_path_factory):
    """Generate a 5-second stereo WAV file with sine waves."""
    sr = 44100
    duration = 5
    t = np.linspace(0, duration, sr * duration, endpoint=False)

    left = 0.3 * np.sin(2 * np.pi * 440 * t)
    right = 0.3 * np.sin(2 * np.pi * 554 * t)
    audio = np.column_stack([left, right]).astype(np.float32)

    path = tmp_path_factory.mktemp("audio") / "test.wav"
    sf.write(str(path), audio, sr)
    return path


@pytest.fixture(scope="session")
def separated_stems(synthetic_wav):
    """Run separation on the synthetic WAV and return the stems directory."""
    from learntoplayit.separate import separate_stems, get_stems_dir

    stems_dir = get_stems_dir(str(synthetic_wav))
    if not stems_dir.exists():
        separate_stems(str(synthetic_wav))
    return stems_dir
