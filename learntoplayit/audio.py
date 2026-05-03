from pathlib import Path

import numpy as np
import soundfile as sf

from .separate import available_stems_from_dir


def load_stem(path: str | Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(path, dtype="float32")
    return audio, sr


def load_all_stems(stems_dir: str | Path) -> tuple[dict[str, np.ndarray], int]:
    stems_dir = Path(stems_dir)
    stems = {}
    sr = None
    for name in available_stems_from_dir(stems_dir):
        audio, stem_sr = load_stem(stems_dir / f"{name}.wav")
        if sr is None:
            sr = stem_sr
        stems[name] = audio
    return stems, sr


def mix_stems(stems: dict[str, np.ndarray], mode: str, selected_part: str) -> np.ndarray:
    if mode == "solo":
        return stems[selected_part].copy()
    elif mode == "mute":
        parts = [audio for name, audio in stems.items() if name != selected_part]
        if len(parts) == 0:
            # trying to solo when only one stem: give zeros
            return np.zeros_like(stems[selected_part])
        return sum_arrays(parts)
    else:  # mix
        return sum_arrays(list(stems.values()))


def sum_arrays(arrays: list[np.ndarray]) -> np.ndarray:
    max_len = max(len(a) for a in arrays)
    result = np.zeros_like(arrays[0], shape=(max_len,) + arrays[0].shape[1:])
    for a in arrays:
        result[:len(a)] += a
    return result
