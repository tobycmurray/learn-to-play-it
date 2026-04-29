"""Smoke tests: verify the package installs and key dependencies import."""


def test_import_package():
    import learntoplayit


def test_import_cli():
    from learntoplayit.cli import main


def test_import_audio():
    from learntoplayit.audio import (
        load_stem,
        load_all_stems,
        time_stretch,
        pitch_shift,
        process_audio,
        mix_stems,
    )


def test_import_separate():
    from learntoplayit.separate import (
        separate_stems,
        ensure_stems,
        stems_exist,
        STEM_NAMES,
    )


def test_import_player():
    from learntoplayit.player import Player, play_interactive


def test_import_numpy():
    import numpy as np


def test_import_soundfile():
    import soundfile as sf


def test_import_pyrubberband():
    import pyrubberband as pyrb


def test_import_sounddevice():
    import sounddevice as sd


def test_import_click():
    import click
