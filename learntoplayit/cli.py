import shutil

import click


def _check_prerequisites():
    missing = []
    for name, hint in [
        ("ffmpeg", "brew install ffmpeg (macOS) / apt install ffmpeg (Linux)"),
    ]:
        if shutil.which(name) is None:
            missing.append(f"  - '{name}': {hint}")
    if missing:
        raise click.ClickException(
            "Missing required tools:\n" + "\n".join(missing)
        )


def _validate_speed_pitch(speed, pitch):
    from .player import SPEED_MIN, SPEED_MAX, PITCH_MIN, PITCH_MAX

    speed_min_pct = int(SPEED_MIN * 100)
    speed_max_pct = int(SPEED_MAX * 100)
    if not (speed_min_pct <= speed <= speed_max_pct):
        raise click.ClickException(f"Speed must be between {speed_min_pct} and {speed_max_pct} (got {speed})")
    if not (PITCH_MIN <= pitch <= PITCH_MAX):
        raise click.ClickException(f"Pitch must be between {PITCH_MIN} and {PITCH_MAX} cents (got {pitch})")


@click.group()
@click.option("--stems-dir", type=click.Path(), default=None, help="Directory for stem cache (default: ./stems)")
@click.pass_context
def main(ctx, stems_dir):
    """Learn to play musical parts from recorded songs."""
    _check_prerequisites()
    if stems_dir is not None:
        from .separate import set_stems_root
        set_stems_root(stems_dir)


@main.command()
@click.argument("audio_file", type=click.Path(exists=True))
def separate(audio_file):
    """Separate a song into individual instrument stems."""
    from .separate import separate_stems, stems_exist, get_stems_dir, STEM_NAMES

    if stems_exist(audio_file):
        stems_dir = get_stems_dir(audio_file)
        click.echo(f"Stems already exist in {stems_dir}/")
    else:
        click.echo(f"Separating {audio_file} into stems (this may take a few minutes)...")
        stems_dir = separate_stems(audio_file)
        click.echo(f"Done. Stems saved to {stems_dir}/")

    for name in STEM_NAMES:
        click.echo(f"  {name}.wav")


@main.command()
@click.argument("audio_file", type=click.Path(exists=True))
def parts(audio_file):
    """List available stems for a song."""
    from .separate import get_stems_dir, STEM_NAMES

    stems_dir = get_stems_dir(audio_file)
    if not stems_dir.exists():
        click.echo(f"No stems found. Run 'ltpi separate {audio_file}' first.")
        raise SystemExit(1)

    click.echo(f"Available parts for {audio_file}:")
    for name in STEM_NAMES:
        stem_path = stems_dir / f"{name}.wav"
        if stem_path.exists():
            click.echo(f"  {name}")


@main.command()
@click.argument("audio_file", type=click.Path(exists=True))
@click.argument("part", type=click.Choice(["vocals", "drums", "bass", "guitar", "piano", "other"]))
@click.option("--speed", type=int, default=50, help="Initial speed as percentage (default: 50)")
@click.option("--pitch", type=int, default=0, help="Initial pitch shift in cents (default: 0)")
def practice(audio_file, part, speed, pitch):
    """Practice a part: isolated, starting at 50% speed."""
    _validate_speed_pitch(speed, pitch)
    from .separate import ensure_stems
    from .player import play_interactive

    stems_dir = ensure_stems(audio_file)
    play_interactive(stems_dir, part, initial_mode="solo", initial_speed=speed / 100, initial_cents=pitch)


@main.command()
@click.argument("audio_file", type=click.Path(exists=True))
def clean(audio_file):
    """Delete cached stems for a song."""
    from .separate import get_stems_dir

    stems_dir = get_stems_dir(audio_file)
    if stems_dir.exists():
        shutil.rmtree(stems_dir)
        click.echo(f"Deleted stems for {audio_file}")
    else:
        click.echo(f"No stems found for {audio_file}")


@main.command("play-along")
@click.argument("audio_file", type=click.Path(exists=True))
@click.argument("part", type=click.Choice(["vocals", "drums", "bass", "guitar", "piano", "other"]))
@click.option("--speed", type=int, default=100, help="Initial speed as percentage (default: 100)")
@click.option("--pitch", type=int, default=0, help="Initial pitch shift in cents (default: 0)")
def play_along(audio_file, part, speed, pitch):
    """Play along with the song, your part removed."""
    _validate_speed_pitch(speed, pitch)
    from .separate import ensure_stems
    from .player import play_interactive

    stems_dir = ensure_stems(audio_file)
    play_interactive(stems_dir, part, initial_mode="mute", initial_speed=speed / 100, initial_cents=pitch)
