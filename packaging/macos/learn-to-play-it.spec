# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

SPEC_PATH = Path(SPEC).resolve()
SPEC_DIR = SPEC_PATH.parent
PROJECT_ROOT = SPEC_DIR.parent.parent

APP_NAME = "Learn To Play It"
BUNDLE_ID = "com.tobycmurray.learntoplayit"

ENTRY_SCRIPT = SPEC_DIR / "ltpi_gui_entry.py"
ICON_FILE = SPEC_DIR / "AppIcon.icns"

if not ENTRY_SCRIPT.exists():
    raise FileNotFoundError(f"Missing entry script: {ENTRY_SCRIPT}")

if not ICON_FILE.exists():
    raise FileNotFoundError(f"Missing app icon: {ICON_FILE}")

datas = []
binaries = []
hiddenimports = []

# Ship the project's own LICENSE in the bundle so the GPL-2 license terms are
# discoverable from the .app itself, not only from the GitHub repo.
datas += [(str(PROJECT_ROOT / "LICENSE"), ".")]

# torchcodec links against libav* (libavutil, libavformat, libavcodec, libswresample, ...)
# from Homebrew's ffmpeg installation. PyInstaller's automatic dependency analysis catches
# the libav* libraries and most of their direct deps, but it MISSES some transitive native
# deps (e.g. libx265, which is referenced via @rpath but not picked up automatically). To
# avoid shipping a bundle with unresolved @rpath references, we walk otool -L recursively
# from ffmpeg's lib directory and bundle every Homebrew-rooted dylib in the closure.
import shutil as _shutil
import subprocess as _subprocess
from pathlib import Path as _Path

if not _shutil.which("ffmpeg"):
    raise FileNotFoundError("ffmpeg not found on PATH; install it (brew install ffmpeg) before building")


def _collect_homebrew_dep_closure(seed_paths):
    """Walk otool -L recursively from seed_paths. Return resolved absolute paths
    of all transitive deps under /opt/homebrew or /usr/local. System libs (in
    /usr/lib, /System) are excluded — macOS guarantees those at runtime.
    """
    seen_real = set()
    queue = list(seed_paths)
    while queue:
        ref = queue.pop()
        if not ref.startswith(("/opt/homebrew/", "/usr/local/")):
            continue
        path = _Path(ref)
        if not path.exists():
            continue
        real = path.resolve()
        if real in seen_real:
            continue
        seen_real.add(real)
        try:
            out = _subprocess.check_output(
                ["otool", "-L", str(real)],
                text=True, stderr=_subprocess.DEVNULL,
            )
        except _subprocess.CalledProcessError:
            continue
        for line in out.splitlines()[1:]:
            dep = line.strip().split(" ", 1)[0]
            if dep.startswith(("/opt/homebrew/", "/usr/local/")):
                queue.append(dep)
    return sorted(seen_real)


_ffmpeg_lib_dir = _Path(_shutil.which("ffmpeg")).resolve().parent.parent / "lib"
_seed = (
    list(_ffmpeg_lib_dir.glob("libav*.dylib"))
    + list(_ffmpeg_lib_dir.glob("libsw*.dylib"))
)
if not _seed:
    raise RuntimeError(
        f"No libav*/libsw* dylibs found in {_ffmpeg_lib_dir}. "
        "Try `brew reinstall ffmpeg`."
    )
_native_deps = _collect_homebrew_dep_closure([str(p) for p in _seed])
print(f"[spec] Bundling {len(_native_deps)} Homebrew native deps "
      f"(transitive closure from {_ffmpeg_lib_dir.name}/lib*av*/lib*sw*)")
binaries += [(str(p), ".") for p in _native_deps]

# Your app/package resources.
resource_candidates = [
    SPEC_DIR / "learntoplayit/resources/app_icon.png",
    PROJECT_ROOT / "learntoplayit/resources/app_icon.png",
]

for resource in resource_candidates:
    if resource.exists():
        datas.append((str(resource), "learntoplayit/resources"))
        break

hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "torchcodec",
    "torchcodec.decoders",
    "torchcodec.decoders._audio_decoder",
    "torchcodec.decoders._decoder",
]

# App/runtime dependencies.
for package in [
    "learntoplayit",
    "demucs",
    "beat_this",
    "torch",
    "torchaudio",
    "torchcodec",
    "pylibrb",
    "sounddevice",
    "soundfile",
    "numpy",
]:
    try:
        hiddenimports += collect_submodules(package)
    except Exception as exc:
        print(f"WARNING: could not collect submodules for {package}: {exc}")

    try:
        datas += collect_data_files(package)
    except Exception as exc:
        print(f"WARNING: could not collect data files for {package}: {exc}")

    try:
        binaries += collect_dynamic_libs(package)
    except Exception as exc:
        print(f"WARNING: could not collect dynamic libs for {package}: {exc}")

excludes = [
    "pytest",
    "tensorboard",
    "tensorflow",
    "matplotlib",
    "IPython",
    "jupyter",
    "notebook",
]

a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(PROJECT_ROOT), str(SPEC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ICON_FILE),
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        # CFBundleShortVersionString, CFBundleVersion, and LSMinimumSystemVersion
        # are set by packaging/macos/patch_info_plist.py post-build, so they
        # always match pyproject.toml and the actually-bundled binaries.
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": (
            "Learn To Play It uses audio input/output features while helping you "
            "learn musical parts from songs."
        ),
    },
)
