import click


@click.group()
def main():
    """Learn to play musical parts from recorded songs."""
    pass


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
def practice(audio_file, part):
    """Practice a part: isolated, starting at 50% speed."""
    from .separate import ensure_stems
    from .player import play_interactive

    stems_dir = ensure_stems(audio_file)
    play_interactive(stems_dir, part, initial_mode="solo", initial_speed=0.5)


@main.command("play-along")
@click.argument("audio_file", type=click.Path(exists=True))
@click.argument("part", type=click.Choice(["vocals", "drums", "bass", "guitar", "piano", "other"]))
def play_along(audio_file, part):
    """Play along with the song, your part removed."""
    from .separate import ensure_stems
    from .player import play_interactive

    stems_dir = ensure_stems(audio_file)
    play_interactive(stems_dir, part, initial_mode="mute", initial_speed=1.0)
