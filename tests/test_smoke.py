"""Smoke tests: verify the package installs and key dependencies import."""

import pytest


def _has_portaudio():
    try:
        import sounddevice  # noqa: F401
        return True
    except OSError:
        return False


needs_portaudio = pytest.mark.skipif(
    not _has_portaudio(), reason="PortAudio library not available"
)


def test_import_package():
    import learntoplayit


def test_import_cli():
    from learntoplayit.cli import main


def test_import_audio():
    from learntoplayit.audio import (
        load_stem,
        load_all_stems,
        mix_stems,
    )


def test_import_separate():
    from learntoplayit.separate import (
        separate_stems,
        ensure_stems,
        stems_exist,
        STEM_NAMES,
    )


@needs_portaudio
def test_import_player():
    from learntoplayit.player import Player, play_interactive


def test_import_numpy():
    import numpy as np


def test_import_soundfile():
    import soundfile as sf


def test_import_pylibrb():
    from pylibrb import RubberBandStretcher, Option


@needs_portaudio
def test_import_sounddevice():
    import sounddevice as sd


def test_import_click():
    import click
