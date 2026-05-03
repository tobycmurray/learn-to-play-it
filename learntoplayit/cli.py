import shutil

import click

from .separate import STEM_NAMES

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


def _parse_device(device):
    if device is None:
        return None
    import sounddevice as sd
    try:
        dev_id = int(device)
    except ValueError:
        dev_id = device
    try:
        info = sd.query_devices(dev_id)
    except Exception:
        raise click.ClickException(f"Unknown audio device: {device!r}. Run 'ltpi devices' to list available devices.")
    if info["max_output_channels"] == 0:
        raise click.ClickException(f"Device {device!r} has no output channels. Run 'ltpi devices' to list output devices.")
    return dev_id


def _run_display(player, gui):
    if gui:
        from .gui import GuiDisplay
        GuiDisplay(player).run()
    else:
        from .display import TerminalDisplay
        TerminalDisplay(player).run()


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
def devices():
    """List available audio output devices."""
    import sounddevice as sd

    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            default = " (default)" if i == sd.default.device[1] else ""
            click.echo(f"  {i}: {dev['name']}{default}")


@main.command("detect-beat")
@click.argument("audio_file", type=click.Path(exists=True))
@click.option("--from", "from_stem", type=click.Choice(STEM_NAMES), default=None, help="Use a specific stem instead of the full mix")
def detect_beat(audio_file, from_stem):
    """Detect beats and downbeats in a song."""
    from .beats import detect_beats, beats_exist

    if from_stem:
        from .separate import stems_exist
        if not stems_exist(audio_file):
            raise click.ClickException(f"Stems not found. Run 'ltpi separate {audio_file}' first to use --from.")

    if beats_exist(audio_file):
        click.echo("Beats already detected. Re-running...")

    click.echo(f"Detecting beats in {audio_file}...")
    result = detect_beats(audio_file, from_stem=from_stem)

    if result is None:
        click.echo("Failed to detect beats.")
    else:
        summary = result["summary"]
        n_beats = len(result["beats"])
        n_downbeats = len(result["downbeats"])
        click.echo(f"Done. {n_beats} beats, {n_downbeats} downbeats.")
        click.echo(f"  Tempo: {summary['bpm']} BPM")
        click.echo(f"  Time signature: {summary['time_signature']}")


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
@click.argument("part", type=click.Choice(STEM_NAMES))
@click.option("--speed", type=int, default=50, help="Initial speed as percentage (default: 50)")
@click.option("--pitch", type=int, default=0, help="Initial pitch shift in cents (default: 0)")
@click.option("--device", type=str, default=None, help="Audio output device (name or index)")
@click.option("--gui", is_flag=True, default=False, help="Launch graphical interface")
def practice(audio_file, part, speed, pitch, device, gui):
    """Practice a part: isolated, starting at 50% speed."""
    _validate_speed_pitch(speed, pitch)
    from .separate import ensure_stems
    from .beats import beats_exist, ensure_beats
    from .player import Player

    stems_dir = ensure_stems(audio_file)
    if not beats_exist(audio_file):
        click.echo("Detecting beats...")
    res = ensure_beats(audio_file)
    if res is None:
        click.echo("Couldn't detect beats. Continuing without click track and count-in.")
    player = Player(stems_dir, part, initial_mode="solo", initial_speed=speed / 100, initial_cents=pitch, device=_parse_device(device))
    _run_display(player, gui)


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
@click.option("--device", type=str, default=None, help="Audio output device (name or index)")
@click.option("--gui", is_flag=True, default=False, help="Launch graphical interface")
def play_along(audio_file, part, speed, pitch, device, gui):
    """Play along with the song, your part removed."""
    _validate_speed_pitch(speed, pitch)
    from .separate import ensure_stems
    from .beats import beats_exist, ensure_beats
    from .player import Player

    stems_dir = ensure_stems(audio_file)
    if not beats_exist(audio_file):
        click.echo("Detecting beats...")
    res = ensure_beats(audio_file)
    if res is None:
        click.echo("Couldn't detect beats. Continuing without click track and count-in.")
    player = Player(stems_dir, part, initial_mode="backing", initial_speed=speed / 100, initial_cents=pitch, device=_parse_device(device))
    _run_display(player, gui)
