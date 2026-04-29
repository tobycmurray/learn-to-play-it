"""Test audio processing: loading, stretching, shifting, mixing."""

import numpy as np
from learntoplayit.audio import (
    load_stem,
    load_all_stems,
    time_stretch,
    pitch_shift,
    process_audio,
    mix_stems,
)
from learntoplayit.separate import STEM_NAMES


def test_load_stem(separated_stems):
    audio, sr = load_stem(separated_stems / "vocals.wav")
    assert isinstance(audio, np.ndarray)
    assert sr > 0
    assert audio.dtype == np.float32


def test_load_all_stems(separated_stems):
    stems, sr = load_all_stems(separated_stems)
    assert sr > 0
    assert set(stems.keys()) == set(STEM_NAMES)
    for name, audio in stems.items():
        assert isinstance(audio, np.ndarray)


def test_time_stretch_slower(separated_stems):
    audio, sr = load_stem(separated_stems / "bass.wav")
    stretched = time_stretch(audio, sr, 0.5)
    assert len(stretched) > len(audio) * 1.5


def test_time_stretch_faster(separated_stems):
    audio, sr = load_stem(separated_stems / "bass.wav")
    stretched = time_stretch(audio, sr, 1.5)
    assert len(stretched) < len(audio) * 0.8


def test_time_stretch_identity(separated_stems):
    audio, sr = load_stem(separated_stems / "bass.wav")
    result = time_stretch(audio, sr, 1.0)
    assert np.array_equal(result, audio)


def test_pitch_shift(separated_stems):
    audio, sr = load_stem(separated_stems / "guitar.wav")
    shifted = pitch_shift(audio, sr, 100)
    assert len(shifted) == len(audio)


def test_pitch_shift_identity(separated_stems):
    audio, sr = load_stem(separated_stems / "guitar.wav")
    result = pitch_shift(audio, sr, 0.0)
    assert np.array_equal(result, audio)


def test_process_audio(separated_stems):
    audio, sr = load_stem(separated_stems / "drums.wav")
    result = process_audio(audio, sr, speed=0.8, cents=-50)
    assert isinstance(result, np.ndarray)
    assert len(result) > len(audio)


def test_mix_solo(separated_stems):
    stems, sr = load_all_stems(separated_stems)
    solo = mix_stems(stems, "solo", "bass")
    assert np.array_equal(solo, stems["bass"])


def test_mix_mute(separated_stems):
    stems, sr = load_all_stems(separated_stems)
    muted = mix_stems(stems, "mute", "bass")
    assert not np.array_equal(muted, stems["bass"])


def test_mix_full(separated_stems):
    stems, sr = load_all_stems(separated_stems)
    full = mix_stems(stems, "mix", "bass")
    assert len(full) > 0
