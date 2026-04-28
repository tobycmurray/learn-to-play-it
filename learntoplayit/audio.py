from pathlib import Path

import numpy as np
import soundfile as sf
import pyrubberband as pyrb

from .separate import STEM_NAMES


def load_stem(path: str | Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(path, dtype="float32")
    return audio, sr


def load_all_stems(stems_dir: str | Path) -> tuple[dict[str, np.ndarray], int]:
    stems_dir = Path(stems_dir)
    stems = {}
    sr = None
    for name in STEM_NAMES:
        audio, stem_sr = load_stem(stems_dir / f"{name}.wav")
        if sr is None:
            sr = stem_sr
        stems[name] = audio
    return stems, sr


def time_stretch(audio: np.ndarray, sr: int, rate: float) -> np.ndarray:
    if rate == 1.0:
        return audio
    return pyrb.time_stretch(audio, sr, rate)


def pitch_shift(audio: np.ndarray, sr: int, cents: float) -> np.ndarray:
    if cents == 0.0:
        return audio
    semitones = cents / 100.0
    return pyrb.pitch_shift(audio, sr, semitones)


def process_audio(audio: np.ndarray, sr: int, speed: float, cents: float) -> np.ndarray:
    result = time_stretch(audio, sr, speed)
    result = pitch_shift(result, sr, cents)
    return result


def mix_stems(stems: dict[str, np.ndarray], mode: str, selected_part: str) -> np.ndarray:
    if mode == "solo":
        return stems[selected_part].copy()
    elif mode == "mute":
        parts = [audio for name, audio in stems.items() if name != selected_part]
        return sum_arrays(parts)
    else:  # mix
        return sum_arrays(list(stems.values()))


def sum_arrays(arrays: list[np.ndarray]) -> np.ndarray:
    max_len = max(len(a) for a in arrays)
    result = np.zeros_like(arrays[0], shape=(max_len,) + arrays[0].shape[1:])
    for a in arrays:
        result[:len(a)] += a
    return result
