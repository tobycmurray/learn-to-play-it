import hashlib
import shutil
from pathlib import Path

STEM_NAMES = ["vocals", "drums", "bass", "guitar", "piano", "other"]
STEMS_ROOT = Path("stems")


def file_hash(audio_file: str) -> str:
    h = hashlib.sha256()
    with open(audio_file, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_stems_dir(audio_file: str) -> Path:
    return STEMS_ROOT / file_hash(audio_file)


def stems_exist(audio_file: str) -> bool:
    stems_dir = get_stems_dir(audio_file)
    return all((stems_dir / f"{s}.wav").exists() for s in STEM_NAMES)


def separate_stems(audio_file: str) -> Path:
    audio_path = Path(audio_file).resolve()
    stems_dir = get_stems_dir(audio_file)

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

    demucs_out = tmp_out / model / audio_path.stem
    stems_dir.mkdir(parents=True, exist_ok=True)
    for stem in STEM_NAMES:
        src = demucs_out / f"{stem}.wav"
        dst = stems_dir / f"{stem}.wav"
        shutil.move(str(src), str(dst))

    shutil.rmtree(str(tmp_out))

    return stems_dir


def ensure_stems(audio_file: str) -> Path:
    if not stems_exist(audio_file):
        return separate_stems(audio_file)
    return get_stems_dir(audio_file)
