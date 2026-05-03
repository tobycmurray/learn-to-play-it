"""Tests for beat detection utilities and count-in computation."""

import numpy as np
import pytest

from learntoplayit.beats import (
    _make_clicks,
    compute_count_in,
    render_click_track,
    CLICK_DURATION,
    CLICK_VOLUME,
    DOWNBEAT_FREQ,
    BEAT_FREQ,
)


SR = 44100
CHANNELS = 2


@pytest.fixture
def beats_data_4_4():
    """Typical 4/4 song at 120 BPM, first downbeat at 0.5s."""
    bpm = 120.0
    interval = 60.0 / bpm  # 0.5s
    beats = [0.5 + i * interval for i in range(32)]
    downbeats = [beats[i] for i in range(0, 32, 4)]
    return {
        "beats": beats,
        "downbeats": downbeats,
        "summary": {"bpm": bpm, "time_signature": "4/4"},
    }


@pytest.fixture
def beats_data_3_4():
    """3/4 song at 100 BPM, first downbeat at 0.3s."""
    bpm = 100.0
    interval = 60.0 / bpm  # 0.6s
    beats = [0.3 + i * interval for i in range(24)]
    downbeats = [beats[i] for i in range(0, 24, 3)]
    return {
        "beats": beats,
        "downbeats": downbeats,
        "summary": {"bpm": bpm, "time_signature": "3/4"},
    }


class TestMakeClicks:

    def test_returns_correct_length(self):
        downbeat, beat, click_samples = _make_clicks(SR)
        expected = int(CLICK_DURATION * SR)
        assert click_samples == expected
        assert len(downbeat) == expected
        assert len(beat) == expected

    def test_dtype_is_float32(self):
        downbeat, beat, _ = _make_clicks(SR)
        assert downbeat.dtype == np.float32
        assert beat.dtype == np.float32

    def test_peak_amplitude_matches_volume(self):
        downbeat, beat, _ = _make_clicks(SR)
        assert abs(downbeat.max() - CLICK_VOLUME) < 0.01
        assert abs(beat.max() - CLICK_VOLUME) < 0.01

    def test_different_sample_rates(self):
        for sr in [22050, 44100, 48000]:
            _, _, click_samples = _make_clicks(sr)
            assert click_samples == int(CLICK_DURATION * sr)


class TestComputeCountIn:

    def test_returns_tuple(self, beats_data_4_4):
        result = compute_count_in(beats_data_4_4, SR, CHANNELS)
        assert result is not None
        track, ci_start = result
        assert isinstance(track, np.ndarray)
        assert isinstance(ci_start, int)

    def test_track_shape(self, beats_data_4_4):
        track, ci_start = compute_count_in(beats_data_4_4, SR, CHANNELS)
        assert track.ndim == 2
        assert track.shape[1] == CHANNELS

    def test_correct_number_of_clicks_4_4(self, beats_data_4_4):
        track, ci_start = compute_count_in(beats_data_4_4, SR, CHANNELS)
        mono = track[:, 0]
        nonzero = np.where(mono != 0)[0]
        clicks = []
        prev = -100
        for idx in nonzero:
            if idx - prev > 10:
                clicks.append(idx)
            prev = idx
        assert len(clicks) == 4

    def test_correct_number_of_clicks_3_4(self, beats_data_3_4):
        track, ci_start = compute_count_in(beats_data_3_4, SR, CHANNELS)
        mono = track[:, 0]
        nonzero = np.where(mono != 0)[0]
        clicks = []
        prev = -100
        for idx in nonzero:
            if idx - prev > 10:
                clicks.append(idx)
            prev = idx
        assert len(clicks) == 3

    def test_last_click_near_first_downbeat(self, beats_data_4_4):
        track, ci_start = compute_count_in(beats_data_4_4, SR, CHANNELS)
        first_downbeat = beats_data_4_4["downbeats"][0]
        beat_interval = 60.0 / beats_data_4_4["summary"]["bpm"]
        expected_last_click_time = first_downbeat - beat_interval
        expected_pos = int(expected_last_click_time * SR) - ci_start
        # Find last click
        mono = track[:, 0]
        nonzero = np.where(mono != 0)[0]
        clicks = []
        prev = -100
        for idx in nonzero:
            if idx - prev > 10:
                clicks.append(idx)
            prev = idx
        # Last click should be within 2 samples of expected position
        assert abs(clicks[-1] - expected_pos) <= 2

    def test_click_spacing_matches_bpm(self, beats_data_4_4):
        track, ci_start = compute_count_in(beats_data_4_4, SR, CHANNELS)
        mono = track[:, 0]
        nonzero = np.where(mono != 0)[0]
        clicks = []
        prev = -100
        for idx in nonzero:
            if idx - prev > 10:
                clicks.append(idx)
            prev = idx
        expected_spacing = int(60.0 / beats_data_4_4["summary"]["bpm"] * SR)
        for i in range(1, len(clicks)):
            spacing = clicks[i] - clicks[i - 1]
            assert abs(spacing - expected_spacing) <= 2

    def test_returns_none_no_downbeats(self):
        data = {"beats": [0.5, 1.0], "downbeats": [], "summary": {"bpm": 120, "time_signature": "4/4"}}
        assert compute_count_in(data, SR, CHANNELS) is None

    def test_returns_none_zero_bpm(self):
        data = {"beats": [0.5, 1.0], "downbeats": [0.5], "summary": {"bpm": 0, "time_signature": "4/4"}}
        assert compute_count_in(data, SR, CHANNELS) is None

    def test_returns_none_missing_summary(self):
        data = {"beats": [0.5, 1.0], "downbeats": [0.5]}
        assert compute_count_in(data, SR, CHANNELS) is None

    def test_index_mapping(self, beats_data_4_4):
        """array_idx = pos_orig - count_in_start; at pos_orig=0, array_idx=-ci_start."""
        track, ci_start = compute_count_in(beats_data_4_4, SR, CHANNELS)
        assert ci_start < 0

    def test_warmup_padding(self, beats_data_4_4):
        """First click should not be at array index 0 (warmup space before it)."""
        track, _ = compute_count_in(beats_data_4_4, SR, CHANNELS)
        mono = track[:, 0]
        first_nonzero = np.argmax(mono != 0)
        assert first_nonzero > 0


class TestRenderClickTrack:

    def test_output_shape(self, beats_data_4_4):
        song_len = SR * 10
        track = render_click_track(beats_data_4_4, song_len, SR, CHANNELS)
        assert track.shape == (song_len, CHANNELS)

    def test_dtype(self, beats_data_4_4):
        track = render_click_track(beats_data_4_4, SR * 10, SR, CHANNELS)
        assert track.dtype == np.float32

    def test_clicks_at_beat_positions(self, beats_data_4_4):
        song_len = SR * 10
        track = render_click_track(beats_data_4_4, song_len, SR, CHANNELS)
        click_samples = int(CLICK_DURATION * SR)
        for beat_time in beats_data_4_4["beats"]:
            sample_pos = int(beat_time * SR)
            if sample_pos + click_samples <= song_len:
                region = track[sample_pos:sample_pos + click_samples, 0]
                assert np.any(region != 0), f"No click at beat position {beat_time}s"

    def test_silence_between_beats(self, beats_data_4_4):
        """Middle of the interval between two beats should be silent."""
        song_len = SR * 10
        track = render_click_track(beats_data_4_4, song_len, SR, CHANNELS)
        beat0 = beats_data_4_4["beats"][0]
        beat1 = beats_data_4_4["beats"][1]
        mid_sample = int((beat0 + beat1) / 2 * SR)
        assert track[mid_sample, 0] == 0

    def test_no_clicks_beyond_song_len(self, beats_data_4_4):
        """With a very short song, beats past the end should not overflow."""
        song_len = SR * 1  # only 1 second
        track = render_click_track(beats_data_4_4, song_len, SR, CHANNELS)
        assert track.shape == (song_len, CHANNELS)

    def test_downbeat_uses_higher_freq(self, beats_data_4_4):
        """Downbeat clicks should use the higher frequency."""
        song_len = SR * 10
        track = render_click_track(beats_data_4_4, song_len, SR, CHANNELS)
        downbeat_click, beat_click, _ = _make_clicks(SR)
        # First beat is a downbeat
        first_beat_pos = int(beats_data_4_4["beats"][0] * SR)
        click_len = int(CLICK_DURATION * SR)
        actual = track[first_beat_pos:first_beat_pos + click_len, 0]
        np.testing.assert_array_almost_equal(actual, downbeat_click, decimal=5)

    def test_non_downbeat_uses_lower_freq(self, beats_data_4_4):
        """Non-downbeat clicks should use the lower frequency."""
        song_len = SR * 10
        track = render_click_track(beats_data_4_4, song_len, SR, CHANNELS)
        _, beat_click, _ = _make_clicks(SR)
        # Second beat is not a downbeat
        second_beat_pos = int(beats_data_4_4["beats"][1] * SR)
        click_len = int(CLICK_DURATION * SR)
        actual = track[second_beat_pos:second_beat_pos + click_len, 0]
        np.testing.assert_array_almost_equal(actual, beat_click, decimal=5)
