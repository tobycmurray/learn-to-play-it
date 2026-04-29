"""Test audio loading and mixing."""

import numpy as np
from learntoplayit.audio import (
    load_stem,
    load_all_stems,
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
