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

# torchcodec links against libav* (libavutil, libavformat, libavcodec, libswresample, ...)
# from Homebrew's ffmpeg installation. PyInstaller picks these up automatically via @rpath
# analysis on torchcodec's dylibs. ffmpeg must be installed via Homebrew at build time so
# those dylibs are available to be bundled, but the ffmpeg/ffprobe binaries themselves are
# not used at runtime.
import shutil as _shutil
if not _shutil.which("ffmpeg"):
    raise FileNotFoundError("ffmpeg not found on PATH; install it (brew install ffmpeg) before building")

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
