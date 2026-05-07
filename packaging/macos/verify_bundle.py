#!/usr/bin/env python3
"""Verify that every @rpath reference in every bundled Mach-O resolves to a
file inside the .app. If any reference points at a missing dylib, fail loudly
at build time rather than letting the user discover it as a launch crash.

This is a guardrail against PyInstaller missing transitive native deps. The
spec walks otool -L recursively to bundle Homebrew's ffmpeg dep closure, but
this script is the belt-and-braces check that nothing slipped through.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
APP = REPO_ROOT / "dist" / "Learn To Play It.app"

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
}

# torchcodec ships per-ABI libs (core, pybind_ops, custom_ops) targeting older
# ffmpeg versions. Only the ones matching the bundled ffmpeg are expected to
# load at runtime; the older ones gracefully fail to load. So unresolved deps
# in those libs (e.g. libavutil.56.dylib referenced by libtorchcodec_core4) are
# not real failures.
IGNORE_REFS_FROM = re.compile(
    r"^libtorchcodec_(core|pybind_ops|custom_ops)[4-7]\.(dylib|so)$"
)


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) in MACHO_MAGICS
    except OSError:
        return False


def install_name_of(path: Path) -> str | None:
    """Return the dylib's own install_name (LC_ID_DYLIB), or None if it has none
    (e.g. for executables and bundle Mach-Os).
    """
    out = subprocess.check_output(["otool", "-D", str(path)], text=True).splitlines()
    return out[1].strip() if len(out) >= 2 else None


def referenced_libs(path: Path):
    """Yield (raw_ref, basename) for each @rpath/<name> dependency.

    Skips the dylib's own install_name self-identification so we don't flag a
    file's own @rpath/<name> identity as a missing dependency.
    """
    self_install_name = install_name_of(path)
    out = subprocess.check_output(["otool", "-L", str(path)], text=True)
    for line in out.splitlines()[1:]:
        ref = line.strip().split(" ", 1)[0]
        if ref == self_install_name:
            continue
        if ref.startswith("@rpath/"):
            yield ref, ref.removeprefix("@rpath/")


def main():
    if not APP.is_dir():
        print(f"App bundle not found: {APP}", file=sys.stderr)
        sys.exit(1)

    contents = APP / "Contents"
    available = {p.name for p in contents.rglob("*") if p.is_file()}

    missing = []
    for path in contents.rglob("*"):
        if not path.is_file() or path.is_symlink() or not is_macho(path):
            continue
        if IGNORE_REFS_FROM.match(path.name):
            continue
        for raw_ref, basename in referenced_libs(path):
            if basename not in available:
                missing.append((path.relative_to(APP), raw_ref))

    if missing:
        print(f"Bundle is incomplete: {len(missing)} unresolved @rpath references.", file=sys.stderr)
        for src, ref in missing:
            print(f"  {src} -> {ref}", file=sys.stderr)
        print("\nThis means a transitive native dep wasn't bundled. The app "
              "will crash on launch for any user.\nFix the spec's "
              "`_collect_homebrew_dep_closure` seed list or add explicit "
              "binaries entries.", file=sys.stderr)
        sys.exit(1)

    print(f"Bundle dependency check OK ({len(available)} files in bundle).")


if __name__ == "__main__":
    main()
