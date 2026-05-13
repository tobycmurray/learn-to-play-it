# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
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


# ---------------------------------------------------------------------------
# Mach-O / dylib helpers
# ---------------------------------------------------------------------------

SYSTEM_PREFIXES = (
    "/usr/lib/",
    "/System/Library/",
)

FFMPEG_DYLIB_RE = re.compile(
    r"^(?:@rpath/|@loader_path/|@executable_path/)?"
    r"(lib(?:avcodec|avformat|avutil|avdevice|avfilter|swscale|swresample)"
    r"\..*\.dylib)$"
)

TORCHCODEC_BACKEND_RE = re.compile(
    r"libtorchcodec_(?:core|custom_ops|pybind_ops)(\d+)(?:\.dylib|\.so)$"
)


def _check_output(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            args,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return ""


def _is_macho(path: Path) -> bool:
    if not path.is_file():
        return False
    return "Mach-O" in _check_output(["file", str(path)])


def _otool_l(path: Path) -> list[str]:
    out = _check_output(["otool", "-L", str(path)])
    if not out:
        return []
    return out.splitlines()[1:]


def _otool_dep_from_line(line: str) -> str:
    return line.strip().split(" ", 1)[0]


def _dylib_minos(path: Path) -> str | None:
    lines = _check_output(["otool", "-l", str(path)]).splitlines()

    for i, line in enumerate(lines):
        if "LC_BUILD_VERSION" in line:
            for sub in lines[i : i + 10]:
                parts = sub.strip().split()
                if len(parts) >= 2 and parts[0] == "minos":
                    return parts[1]

        if "LC_VERSION_MIN_MACOSX" in line:
            for sub in lines[i : i + 10]:
                parts = sub.strip().split()
                if len(parts) >= 2 and parts[0] == "version":
                    return parts[1]

    return None


def _resolve_vendor_dep(ref: str, vendor_lib_dir: Path) -> Path | None:
    """Resolve a dependency reference against the vendor library directory.

    This is intentionally conservative: it only resolves references that live
    inside the FFmpeg vendor directory. System libraries are ignored.
    """
    if ref.startswith(SYSTEM_PREFIXES):
        return None

    if ref.startswith("@rpath/"):
        candidate = vendor_lib_dir / ref.removeprefix("@rpath/")
    elif ref.startswith("@loader_path/"):
        candidate = vendor_lib_dir / ref.removeprefix("@loader_path/")
    elif ref.startswith("@executable_path/"):
        candidate = vendor_lib_dir / ref.removeprefix("@executable_path/")
    elif ref.startswith("/"):
        path = Path(ref)
        try:
            path.relative_to(vendor_lib_dir)
        except ValueError:
            return None
        candidate = path
    else:
        candidate = vendor_lib_dir / ref

    return candidate if candidate.exists() else None


# ---------------------------------------------------------------------------
# TorchCodec / FFmpeg vendoring
# ---------------------------------------------------------------------------

def _torchcodec_dir() -> Path:
    spec = importlib.util.find_spec("torchcodec")
    if spec is None or spec.origin is None:
        raise RuntimeError(
            "Could not find installed torchcodec package. "
            "Install requirements before running PyInstaller."
        )
    return Path(spec.origin).resolve().parent


def _torchcodec_ffmpeg_refs_by_backend() -> dict[int, set[str]]:
    """Discover FFmpeg dylibs required by each TorchCodec backend.

    TorchCodec ships multiple FFmpeg backend variants, such as:
      libtorchcodec_core4.dylib
      libtorchcodec_core5.dylib
      ...
      libtorchcodec_core8.dylib

    Each backend links against a different FFmpeg ABI family. We do not want to
    require all of them. We only need one backend whose FFmpeg dylibs are
    present in FFMPEG_LIB_DIR.
    """
    root = _torchcodec_dir()
    refs_by_backend: dict[int, set[str]] = {}

    for path in root.rglob("*"):
        if not _is_macho(path):
            continue

        backend_match = TORCHCODEC_BACKEND_RE.match(path.name)
        if not backend_match:
            continue

        backend = int(backend_match.group(1))

        for line in _otool_l(path):
            dep = _otool_dep_from_line(line)
            ffmpeg_match = FFMPEG_DYLIB_RE.match(dep)
            if ffmpeg_match:
                refs_by_backend.setdefault(backend, set()).add(ffmpeg_match.group(1))

    if not refs_by_backend:
        raise RuntimeError(
            f"Could not discover TorchCodec FFmpeg backend references under {root}"
        )

    return refs_by_backend


def _select_torchcodec_backend(vendor_lib_dir: Path) -> tuple[int, set[str]]:
    refs_by_backend = _torchcodec_ffmpeg_refs_by_backend()

    print("[spec] TorchCodec FFmpeg backends discovered:")
    for backend in sorted(refs_by_backend):
        refs = sorted(refs_by_backend[backend])
        available = refs and all((vendor_lib_dir / name).exists() for name in refs)
        status = "available" if available else "missing dylibs"
        print(f"[spec]   backend {backend}: {status}")
        for name in refs:
            print(f"[spec]     {name}")

    # Prefer the newest backend that the vendor FFmpeg directory fully satisfies.
    for backend in sorted(refs_by_backend, reverse=True):
        refs = refs_by_backend[backend]
        if refs and all((vendor_lib_dir / name).exists() for name in refs):
            print(f"[spec] Selected TorchCodec FFmpeg backend: {backend}")
            return backend, refs

    raise RuntimeError(
        "No TorchCodec FFmpeg backend is fully satisfied by FFMPEG_LIB_DIR.\n"
        f"FFMPEG_LIB_DIR={vendor_lib_dir}\n"
        "Install a compatible FFmpeg in the vendor env, for example:\n"
        "  conda install -y -n ltp-ffmpeg -c conda-forge 'ffmpeg>=8,<9'"
    )


def _collect_vendor_closure(seed_paths: list[Path], vendor_lib_dir: Path) -> list[Path]:
    """Collect seed dylibs plus their vendor-local dependencies.

    Important: do not collapse symlinks away. TorchCodec may ask dyld for the
    ABI-name file, e.g. libavdevice.62.dylib, while that file may be a symlink
    to libavdevice.62.3.101.dylib. We include both names when present.
    """
    queue = list(seed_paths)
    collected: list[Path] = []
    seen_paths: set[str] = set()

    def add(path: Path) -> None:
        key = str(path)
        if key not in seen_paths and path.exists():
            seen_paths.add(key)
            collected.append(path)

    while queue:
        path = queue.pop(0)
        if not path.exists():
            continue

        add(path)

        real = path.resolve()
        try:
            real.relative_to(vendor_lib_dir)
        except ValueError:
            real = path

        if real.exists():
            add(real)

        inspect_path = real if real.exists() else path
        for line in _otool_l(inspect_path):
            dep = _otool_dep_from_line(line)
            dep_path = _resolve_vendor_dep(dep, vendor_lib_dir)
            if dep_path and str(dep_path) not in seen_paths:
                queue.append(dep_path)

    return collected


def _collect_conda_ffmpeg_dylibs() -> list[tuple[str, str]]:
    ffmpeg_lib_dir_env = os.environ.get("FFMPEG_LIB_DIR")
    if not ffmpeg_lib_dir_env:
        raise RuntimeError(
            "FFMPEG_LIB_DIR is not set. build_app.sh should set this to the "
            "conda-forge FFmpeg environment's lib directory."
        )

    vendor_lib_dir = Path(ffmpeg_lib_dir_env).resolve()
    if not vendor_lib_dir.exists():
        raise RuntimeError(f"FFMPEG_LIB_DIR does not exist: {vendor_lib_dir}")

    backend, refs = _select_torchcodec_backend(vendor_lib_dir)

    seeds = [vendor_lib_dir / name for name in sorted(refs)]
    dylibs = _collect_vendor_closure(seeds, vendor_lib_dir)

    print(f"[spec] Bundling {len(dylibs)} FFmpeg/vendor dylibs from {vendor_lib_dir}")
    for path in dylibs:
        print(f"[spec]   {path.name} minos={_dylib_minos(path)}")

    globals()["_SELECTED_TORCHCODEC_FFMPEG_BACKEND"] = backend

    # Destination "." means PyInstaller places these into Contents/Frameworks
    # in the final .app.
    return [(str(path), ".") for path in dylibs]


def _filter_torchcodec_dynamic_libs(dynamic_libs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Remove unused TorchCodec FFmpeg backend binaries.

    If we selected backend 8, keep:
      libtorchcodec_core8.dylib
      libtorchcodec_custom_ops8.dylib
      libtorchcodec_pybind_ops8.so

    and skip backend 4/5/6/7 binaries. This avoids verify_bundle.py failing on
    unused TorchCodec binaries that reference FFmpeg ABI versions we are not
    shipping.
    """
    selected = globals().get("_SELECTED_TORCHCODEC_FFMPEG_BACKEND")
    if selected is None:
        return dynamic_libs

    kept: list[tuple[str, str]] = []
    skipped: list[str] = []

    for src, dest in dynamic_libs:
        name = Path(src).name
        match = TORCHCODEC_BACKEND_RE.match(name)

        if match and int(match.group(1)) != selected:
            skipped.append(name)
            continue

        kept.append((src, dest))

    if skipped:
        print("[spec] Skipping unused TorchCodec FFmpeg backend binaries:")
        for name in sorted(skipped):
            print(f"[spec]   {name}")

    return kept


binaries += _collect_conda_ffmpeg_dylibs()


# ---------------------------------------------------------------------------
# App resources
# ---------------------------------------------------------------------------

resource_candidates = [
    SPEC_DIR / "learntoplayit/resources/app_icon.png",
    PROJECT_ROOT / "learntoplayit/resources/app_icon.png",
]

for resource in resource_candidates:
    if resource.exists():
        datas.append((str(resource), "learntoplayit/resources"))
        break


# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------

hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "torchcodec",
    "torchcodec.decoders",
    "torchcodec.decoders._audio_decoder",
    "torchcodec.decoders._decoder",
]


# ---------------------------------------------------------------------------
# App/runtime dependencies
# ---------------------------------------------------------------------------

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
        package_binaries = collect_dynamic_libs(package)
        if package == "torchcodec":
            package_binaries = _filter_torchcodec_dynamic_libs(package_binaries)
        binaries += package_binaries
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
        # CFBundleShortVersionString, CFBundleVersion, and
        # LSMinimumSystemVersion are set by patch_info_plist.py post-build, so
        # they match pyproject.toml and the actually bundled binaries.
        "NSHighResolutionCapable": True,
    },
)