import numpy as np

from learntoplayit.display import TerminalDisplay
from learntoplayit.player import WaveformData


def _waveform_data(viewport_start_bin, **kwargs):
    return WaveformData(
        bins=np.zeros(11, dtype=np.float32),
        beat_cols=kwargs.get("beat_cols", []),
        downbeat_cols=kwargs.get("downbeat_cols", []),
        viewport_start_bin=viewport_start_bin,
        loop_start_col=kwargs.get("loop_start_col"),
        loop_end_col=kwargs.get("loop_end_col"),
        loop_active=False,
        total_bins=200,
    )


def test_tui_marker_cells_follow_song_chunks():
    wd = _waveform_data(viewport_start_bin=99.3)

    # These are both in global bin/chunk 100, despite being distinct precise
    # positions inside that chunk.
    beat_col = 100.1 - wd.viewport_start_bin
    loop_col = 100.8 - wd.viewport_start_bin

    assert TerminalDisplay._chunk_cell_for_col(wd, beat_col) == 1
    assert TerminalDisplay._chunk_cell_for_col(wd, loop_col) == 1


def test_tui_marker_line_keeps_same_chunk_markers_together():
    wd = _waveform_data(
        viewport_start_bin=99.3,
        downbeat_cols=[100.1 - 99.3],
        loop_end_col=100.8 - 99.3,
    )

    marker_line = TerminalDisplay._marker_line(wd)

    assert marker_line[2 + 1] == "]"
    assert "|" not in marker_line
    assert marker_line.count("]") == 1
