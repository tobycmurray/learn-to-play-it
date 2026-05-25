import numpy as np
import pytest

from learntoplayit.gui import ViewportZoom, _peak_per_pixel
from learntoplayit.player import NUDGE_SECONDS


SONG = 300.0  # arbitrary "long enough" song duration in seconds


class TestViewportZoom:

    def test_default_seconds_maps_to_expected_bin_count(self):
        z = ViewportZoom(5.0)
        assert z.num_bins(SONG) == round(5.0 / NUDGE_SECONDS)

    def test_zoom_out_widens(self):
        z = ViewportZoom(5.0)
        before = z.num_bins(SONG)
        z.zoom(2.0, SONG)
        assert z.num_bins(SONG) == before * 2

    def test_zoom_in_narrows(self):
        z = ViewportZoom(5.0)
        before = z.num_bins(SONG)
        z.zoom(0.5, SONG)
        assert z.num_bins(SONG) == before // 2

    def test_min_bins_clamp_on_extreme_zoom_in(self):
        z = ViewportZoom(5.0)
        for _ in range(50):
            z.zoom(0.5, SONG)
        assert z.num_bins(SONG) == ViewportZoom.MIN_BINS

    def test_max_clamp_on_extreme_zoom_out(self):
        z = ViewportZoom(5.0)
        for _ in range(50):
            z.zoom(2.0, SONG)
        # Viewport can't exceed the song's bin count.
        assert z.num_bins(SONG) == int(SONG / NUDGE_SECONDS)

    def test_short_song_max_clamp_respects_min_bins_floor(self):
        # If a song is shorter than MIN_BINS * NUDGE_SECONDS, the floor still applies.
        short = ViewportZoom.MIN_BINS * NUDGE_SECONDS / 2
        z = ViewportZoom(5.0)
        for _ in range(50):
            z.zoom(2.0, short)
        assert z.num_bins(short) == ViewportZoom.MIN_BINS

    def test_zoom_intent_accumulates_below_bin_resolution(self):
        """The whole point of storing seconds as a float: small zoom ticks
        that individually round to the same bin count must accumulate, so
        repeated ticks eventually cross a bin boundary. If someone changed
        the internal storage to int-bins, the first sub-resolution tick
        would drop a bin immediately and subsequent ticks would compound
        the error — this test pins the float-intent invariant.
        """
        z = ViewportZoom(2.0)  # 40 bins
        assert z.num_bins(SONG) == 40
        # 0.995 per tick: 2.0 → 1.99 → 1.98... each step changes seconds
        # by less than one bin's width (0.05). Bin count stays at 40 for
        # the first couple of ticks then drops.
        z.zoom(0.995, SONG)
        assert z.num_bins(SONG) == 40
        z.zoom(0.995, SONG)
        assert z.num_bins(SONG) == 40
        z.zoom(0.995, SONG)
        assert z.num_bins(SONG) == 39

    def test_zoom_in_then_out_returns_to_origin(self):
        z = ViewportZoom(5.0)
        before = z.num_bins(SONG)
        z.zoom(0.7, SONG)
        z.zoom(1 / 0.7, SONG)
        assert z.num_bins(SONG) == before


class TestPeakPerPixel:

    def test_output_length_is_w(self):
        bins = np.zeros(11, dtype=np.float32)
        peaks = _peak_per_pixel(bins, w=50, bin_offset=0.0)
        assert peaks.shape == (50,)

    def test_basic_peak_identification(self):
        # num_bins = 4, w = 4, one bin per pixel.
        bins = np.array([0.0, 0.5, 0.0, 0.9, 0.0], dtype=np.float32)  # bins[4] is the +1 partial
        peaks = _peak_per_pixel(bins, w=4, bin_offset=0.0)
        # Each pixel covers exactly one bin (last covers bins[3:5]).
        assert peaks[0] == pytest.approx(0.0)
        assert peaks[1] == pytest.approx(0.5)
        assert peaks[2] == pytest.approx(0.0)
        # peaks[3] covers bins[3] AND the +1 partial-edge bin[4].
        assert peaks[3] == pytest.approx(0.9)

    def test_rightmost_pixel_includes_partial_edge_bin(self):
        """The +1 bin in `bins` (past the canonical viewport width) must
        be picked up by the rightmost pixel — otherwise the right-edge
        smooth-scroll behavior breaks. Putting the only non-zero amplitude
        in the partial bin verifies it's not silently dropped.
        """
        bins = np.zeros(11, dtype=np.float32)
        bins[10] = 0.7  # only the +1 partial-edge bin is non-zero
        peaks = _peak_per_pixel(bins, w=10, bin_offset=0.0)
        assert peaks[-1] == pytest.approx(0.7)
        assert peaks[:-1].max() == pytest.approx(0.0)

    def test_peak_per_pixel_when_zoomed_in_repeats_bin(self):
        # Zoomed in: bins_per_pixel < 1, multiple pixels share one bin.
        bins = np.array([0.0, 0.4, 0.0], dtype=np.float32)  # num_bins=2
        peaks = _peak_per_pixel(bins, w=8, bin_offset=0.0)
        # bpp = 0.25. Pixels 0-3 → bin 0; pixels 4-7 → bin 1.
        # Output length is 8; peak follows the source bin per group.
        assert peaks.shape == (8,)
        # The high bin should appear somewhere in the second half.
        assert peaks[4:].max() == pytest.approx(0.4)

    def test_bin_offset_affects_pixel_assignment(self):
        # bpp = 0.6 puts the same source bin into different pixel groups
        # depending on bin_offset; pins that bin_offset is used (not zero'd).
        bins = np.array([0.8, 0.0, 0.0, 0.0], dtype=np.float32)  # num_bins=3
        no_offset = _peak_per_pixel(bins, w=5, bin_offset=0.0)
        with_offset = _peak_per_pixel(bins, w=5, bin_offset=0.5)
        # Both still have 0.8 somewhere (the bin is in-viewport), but the
        # pixel that lights up depends on bin_offset.
        assert no_offset.max() == pytest.approx(0.8)
        assert with_offset.max() == pytest.approx(0.8)
        # And the patterns aren't identical:
        assert not np.array_equal(no_offset, with_offset)
