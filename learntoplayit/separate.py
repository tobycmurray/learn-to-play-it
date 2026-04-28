import shutil
from pathlib import Path

STEM_NAMES = ["vocals", "drums", "bass", "guitar", "piano", "other"]
STEMS_ROOT = Path("stems")


def get_stems_dir(audio_file: str) -> Path:
    name = Path(audio_file).stem
    return STEMS_ROOT / name


def stems_exist(audio_file: str) -> bool:
    stems_dir = get_stems_dir(audio_file)
    return all((stems_dir / f"{s}.wav").exists() for s in STEM_NAMES)


def separate_stems(audio_file: str) -> Path:
    audio_path = Path(audio_file).resolve()
    stems_dir = get_stems_dir(audio_file)

    # Demucs writes to <out>/<model>/<track>/<stem>.wav
    # We use a temp output dir, then move stems to our cache layout.
    from demucs.separate import main as demucs_main

    model = "htdemucs_6s"
    tmp_out = STEMS_ROOT / "_tmp"
    tmp_out.mkdir(parents=True, exist_ok=True)

    demucs_main([
        "-n", model,
        "--float32",
        "-o", str(tmp_out),
        str(audio_path),
    ])

    # Move from demucs output structure to our flat layout
    demucs_out = tmp_out / model / audio_path.stem
    stems_dir.mkdir(parents=True, exist_ok=True)
    for stem in STEM_NAMES:
        src = demucs_out / f"{stem}.wav"
        dst = stems_dir / f"{stem}.wav"
        shutil.move(str(src), str(dst))

    # Clean up demucs temp dir
    shutil.rmtree(str(tmp_out))

    return stems_dir


def ensure_stems(audio_file: str) -> Path:
    if not stems_exist(audio_file):
        return separate_stems(audio_file)
    return get_stems_dir(audio_file)
