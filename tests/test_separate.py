"""Test that source separation produces valid stems."""

from learntoplayit.separate import STEM_NAMES


def test_all_stems_exist(separated_stems):
    for name in STEM_NAMES:
        stem_path = separated_stems / f"{name}.wav"
        assert stem_path.exists(), f"Missing stem: {name}.wav"


def test_stems_are_valid_audio(separated_stems):
    import soundfile as sf

    for name in STEM_NAMES:
        audio, sr = sf.read(str(separated_stems / f"{name}.wav"))
        assert sr > 0
        assert len(audio) > 0


def test_stems_have_consistent_length(separated_stems):
    import soundfile as sf

    lengths = []
    for name in STEM_NAMES:
        audio, _ = sf.read(str(separated_stems / f"{name}.wav"))
        lengths.append(len(audio))

    assert max(lengths) - min(lengths) < 100, "Stems have inconsistent lengths"


def test_stems_exist_function(synthetic_wav):
    from learntoplayit.separate import stems_exist
    assert stems_exist(str(synthetic_wav))


def test_parts_command(synthetic_wav):
    from click.testing import CliRunner
    from learntoplayit.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["parts", str(synthetic_wav)])
    assert result.exit_code == 0
    for name in STEM_NAMES:
        assert name in result.output


def test_clean_command(synthetic_wav):
    from click.testing import CliRunner
    from learntoplayit.cli import main
    from learntoplayit.separate import get_stems_dir, stems_exist

    stems_dir = get_stems_dir(str(synthetic_wav))
    assert stems_dir.exists()

    runner = CliRunner()
    result = runner.invoke(main, ["clean", str(synthetic_wav)])
    assert result.exit_code == 0
    assert "Deleted" in result.output
    assert not stems_dir.exists()

    result = runner.invoke(main, ["clean", str(synthetic_wav)])
    assert result.exit_code == 0
    assert "No stems found" in result.output
