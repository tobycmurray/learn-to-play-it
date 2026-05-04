import hashlib
import shutil
from pathlib import Path
import soundfile as sf
import numpy as np

STEM_NAMES = ["vocals", "drums", "bass", "guitar", "piano", "other"]
STEMS_ROOT = Path("stems")


def set_stems_root(path: str | Path):
    global STEMS_ROOT
    STEMS_ROOT = Path(path)


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
    return any((stems_dir / f"{s}.wav").exists() for s in STEM_NAMES)

def available_stems_from_dir(stems_dir: Path) -> list[str]:
    actual_stems = []
    for stem in STEM_NAMES:
        if (Path(stems_dir) / f"{stem}.wav").exists():
            actual_stems.append(stem)
    return actual_stems

def available_stems(audio_file: str) -> list[str]:
    stems_dir = get_stems_dir(audio_file)
    return available_stems_from_dir(stems_dir)

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
        audio, sr = sf.read(src, dtype="float32")
        # filter out anything that is basically silence
        m = np.abs(audio).max()
        if m >= 0.1:
            dst = stems_dir / f"{stem}.wav"
            shutil.move(str(src), str(dst))

    shutil.rmtree(str(tmp_out))

    return stems_dir


def ensure_stems(audio_file: str) -> Path:
    if not stems_exist(audio_file):
        return separate_stems(audio_file)
    return get_stems_dir(audio_file)
