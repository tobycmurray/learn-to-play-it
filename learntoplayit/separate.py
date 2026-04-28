from pathlib import Path

STEM_NAMES = ["vocals", "drums", "bass", "other"]
STEMS_ROOT = Path("stems")


def get_stems_dir(audio_file: str) -> Path:
    name = Path(audio_file).stem
    return STEMS_ROOT / name


def stems_exist(audio_file: str) -> bool:
    stems_dir = get_stems_dir(audio_file)
    return all((stems_dir / f"{s}.wav").exists() for s in STEM_NAMES)


def separate_stems(audio_file: str) -> Path:
    raise NotImplementedError("Phase 2")


def ensure_stems(audio_file: str) -> Path:
    if not stems_exist(audio_file):
        return separate_stems(audio_file)
    return get_stems_dir(audio_file)
