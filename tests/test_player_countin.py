"""Tests for Player count-in and _read_block mechanics.

These tests mock the audio output so no PortAudio is needed.
"""

import numpy as np
import pytest
import soundfile as sf

from learntoplayit.beats import compute_count_in, render_click_track, detect_beats


SR = 44100
CHANNELS = 2
DURATION = 5


@pytest.fixture(scope="module")
def stems_with_beats(tmp_path_factory):
    """Create a fake stems directory with audio files and beats.json."""
    from learntoplayit.separate import STEM_NAMES

    stems_dir = tmp_path_factory.mktemp("stems")
    t = np.linspace(0, DURATION, SR * DURATION, endpoint=False)
    audio = np.column_stack([
        0.3 * np.sin(2 * np.pi * 440 * t),
        0.3 * np.sin(2 * np.pi * 554 * t),
    ]).astype(np.float32)

    for name in STEM_NAMES:
        sf.write(str(stems_dir / f"{name}.wav"), audio, SR)

    # Write beats.json: 120 BPM, 4/4, first downbeat at 0.5s
    import json
    bpm = 120.0
    interval = 60.0 / bpm
    beats = [0.5 + i * interval for i in range(int((DURATION - 0.5) / interval))]
    downbeats = [beats[i] for i in range(0, len(beats), 4)]
    analysis_dir = stems_dir / "analysis"
    analysis_dir.mkdir()
    with open(analysis_dir / "beats.json", "w") as f:
        json.dump({
            "beats": beats,
            "downbeats": downbeats,
            "summary": {"bpm": bpm, "time_signature": "4/4"},
        }, f)

    return stems_dir


@pytest.fixture
def player(stems_with_beats):
    """Create a Player without starting audio output."""
    from learntoplayit.player import Player
    return Player(str(stems_with_beats), "vocals", initial_mode="solo", initial_speed=1.0)


class TestPlayerCountInState:

    def test_count_in_loaded(self, player):
        assert player._count_in_track is not None
        assert player._count_in_samples > 0

    def test_count_in_enabled_by_default(self, player):
        assert player.count_in_enabled is True

    def test_start_pos_negative_when_enabled(self, player):
        assert player._start_pos < 0
        assert player._start_pos == -player._count_in_samples

    def test_start_pos_zero_when_disabled(self, player):
        player.count_in_enabled = False
        assert player._start_pos == 0

    def test_toggle_count_in(self, player):
        assert player.count_in_enabled is True
        player.toggle_count_in()
        assert player.count_in_enabled is False
        player.toggle_count_in()
        assert player.count_in_enabled is True

    def test_toggle_count_in_noop_when_unavailable(self, player):
        player._count_in_track = None
        player.count_in_enabled = False
        player.toggle_count_in()
        assert player.count_in_enabled is False


class TestReadBlock:

    def test_positive_territory_shape(self, player):
        block = player._read_block(0, 1024)
        assert block.shape == (1024, CHANNELS)

    def test_negative_territory_shape(self, player):
        block = player._read_block(-player._count_in_samples, 1024)
        assert block.shape == (1024, CHANNELS)

    def test_straddling_zero_shape(self, player):
        block = player._read_block(-512, 1024)
        assert block.shape == (1024, CHANNELS)

    def test_fully_negative_is_mostly_silent(self, player):
        """In deep negative territory (before count-in clicks), audio is near-silent."""
        player.count_in_enabled = False
        block = player._read_block(-player._count_in_samples, 1024)
        assert np.allclose(block, 0)

    def test_straddling_block_has_audio_in_second_half(self, player):
        """Block from -512 to +512 should have stems audio in the second half."""
        player.count_in_enabled = False
        player.click_active = False
        block = player._read_block(-512, 1024)
        # First 512 samples should be silence
        assert np.allclose(block[:512], 0)
        # Second 512 samples should have audio from the mix
        assert not np.allclose(block[512:], 0)

    def test_count_in_overlay_present_in_negative(self, player):
        """With count-in enabled, the negative region should contain click data."""
        player.count_in_enabled = True
        # Find where the first count-in click is
        mono = player._count_in_track[:, 0]
        first_nonzero = int(np.argmax(mono != 0))
        # Read a block that covers that click
        pos = first_nonzero - player._count_in_samples
        block = player._read_block(pos, 1024)
        assert not np.allclose(block, 0)

    def test_count_in_not_present_when_disabled(self, player):
        """With count-in disabled, negative territory should be silent."""
        player.count_in_enabled = False
        player.click_active = False
        block = player._read_block(-player._count_in_samples, 1024)
        assert np.allclose(block, 0)

    def test_positive_territory_includes_click_track(self, player):
        """When click is active, blocks in positive territory include click data."""
        player.click_active = True
        player.count_in_enabled = False
        # Find a beat position
        first_beat_pos = int(0.5 * SR)  # first beat at 0.5s
        click_samples = int(0.02 * SR)
        block_with_click = player._read_block(first_beat_pos, click_samples)
        player.click_active = False
        block_no_click = player._read_block(first_beat_pos, click_samples)
        # They should differ (click was added)
        assert not np.allclose(block_with_click, block_no_click)


class TestRestart:

    def test_restart_with_count_in(self, player):
        player.count_in_enabled = True
        player.pos_orig = 50000
        player.restart()
        assert player.pos_orig == -player._count_in_samples

    def test_restart_without_count_in(self, player):
        player.count_in_enabled = False
        player.pos_orig = 50000
        player.restart()
        assert player.pos_orig == 0

    def test_restart_with_loop_ignores_count_in(self, player):
        from learntoplayit.player import LoopRegion
        player.count_in_enabled = True
        player.loop = LoopRegion(start_orig=10000, end_orig=20000, active=True)
        player.pos_orig = 50000
        player.restart()
        assert player.pos_orig == 10000
        player.loop = None
