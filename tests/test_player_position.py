"""Tests for the listener-position derivation in the producer/consumer cursor model.

These tests cover the trickiest corner of player.py: the `_compute_listener_pos`
function that translates the producer cursor (where the feeder will read next)
into the listener position (where audio is currently being heard), accounting
for buffered audio and loop wrapping.

The function is pure, so these tests construct inputs directly without
spinning up a Player or audio stream.
"""

from learntoplayit.player import _compute_listener_pos


# ---------- non-looping playback ----------

def test_no_loop_no_buffer():
    """Listener position == producer position when nothing is buffered."""
    assert _compute_listener_pos(pos_orig=1000, buffered_orig=0, loop_bounds=None) == 1000


def test_no_loop_with_buffer():
    """Listener trails producer by buffered amount."""
    assert _compute_listener_pos(pos_orig=1000, buffered_orig=200, loop_bounds=None) == 800


def test_no_loop_buffered_exceeds_pos():
    """Buffered exceeding pos_orig clamps to 0 (e.g. start of song)."""
    assert _compute_listener_pos(pos_orig=100, buffered_orig=500, loop_bounds=None) == 0


# ---------- looping playback ----------

def test_loop_inside_no_buffer():
    """Listener == producer when both are inside the loop with no buffering."""
    assert _compute_listener_pos(
        pos_orig=5000, buffered_orig=0, loop_bounds=(1000, 9000)
    ) == 5000


def test_loop_inside_with_buffer():
    """No wrap needed when listener is still inside the loop."""
    assert _compute_listener_pos(
        pos_orig=5000, buffered_orig=200, loop_bounds=(1000, 9000)
    ) == 4800


def test_loop_just_after_feeder_wrap():
    """Right after the feeder wraps end → start, the buffer still holds audio
    for samples just before end. The wrap formula reports a position 'near
    end' so the displayed position matches what's audible.
    """
    # Loop [1000, 5000], pos_orig was just reset to 1000 (start), buffer
    # holds 300 samples generated for the tail of the loop just before wrap.
    # Audible position: should be 4700 (= end - 300).
    assert _compute_listener_pos(
        pos_orig=1000, buffered_orig=300, loop_bounds=(1000, 5000)
    ) == 4700


def test_loop_at_exactly_loop_end_does_not_wrap():
    """Regression: setting loop end at the current playhead while paused
    leaves pos_orig == end. The wrap formula must NOT wrap in this case
    (would jump apparent position to start)."""
    assert _compute_listener_pos(
        pos_orig=5000, buffered_orig=0, loop_bounds=(1000, 5000)
    ) == 5000


def test_loop_at_exactly_loop_start():
    """pos_orig at loop start (no buffer) reports loop start, not wrap."""
    assert _compute_listener_pos(
        pos_orig=1000, buffered_orig=0, loop_bounds=(1000, 5000)
    ) == 1000


def test_loop_far_underflow_after_wrap():
    """Underflow by more than one loop iteration: % loop_len handles it."""
    # Loop [1000, 5000] (loop_len 4000). pos_orig = 1000, buffered = 5000.
    # pos = max(0, 1000 - 5000) = 0, then wrap: 1000 + (0 - 1000) % 4000 = 4000.
    # Audibly: 5 underlying iterations (5000) of overlap means audible position
    # is at end - (5000 % 4000) = 5000 - 1000 = 4000. Same answer.
    assert _compute_listener_pos(
        pos_orig=1000, buffered_orig=5000, loop_bounds=(1000, 5000)
    ) == 4000


def test_loop_zero_length_does_nothing():
    """Defensive: degenerate loop bounds (start == end) leave the position alone."""
    assert _compute_listener_pos(
        pos_orig=2000, buffered_orig=500, loop_bounds=(3000, 3000)
    ) == 1500


def test_loop_inactive_means_no_loop():
    """When loop_bounds is None the loop math is skipped entirely."""
    # Even if pos would have triggered a wrap with bounds, no bounds means
    # no wrap. Returns the simple producer-minus-buffer calculation.
    assert _compute_listener_pos(
        pos_orig=500, buffered_orig=200, loop_bounds=None
    ) == 300
