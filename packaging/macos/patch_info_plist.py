#!/usr/bin/env python3
"""Patch the .app's Info.plist with values derived from the build itself.

Run after PyInstaller, before signing — the signing pass covers the Info.plist,
so any subsequent edit would invalidate the signature.

What it sets:
  CFBundleShortVersionString / CFBundleVersion: from pyproject.toml [project] version
  LSMinimumSystemVersion: the highest `minos` required by any bundled Mach-O file
"""
import plistlib
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
APP = REPO_ROOT / "dist" / "Learn To Play It.app"
INFO_PLIST = APP / "Contents" / "Info.plist"

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",  # 64-bit
    b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",  # 32-bit
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # universal/fat
}
MIN_RE = re.compile(r"minos\s+(\d+)\.(\d+)(?:\.(\d+))?")


def project_version() -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return pyproject["project"]["version"]


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) in MACHO_MAGICS
    except OSError:
        return False


def highest_minos() -> str:
    max_v = (0, 0, 0)
    max_source = None
    count = 0
    for path in (APP / "Contents").rglob("*"):
        if not path.is_file() or path.is_symlink() or not is_macho(path):
            continue
        count += 1
        result = subprocess.run(
            ["otool", "-l", str(path)],
            capture_output=True, text=True, check=False,
        )
        for m in MIN_RE.finditer(result.stdout):
            v = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
            if v > max_v:
                max_v = v
                max_source = path.name
    if max_v == (0, 0, 0):
        raise RuntimeError(f"No minos found across {count} Mach-O files")
    print(f"Scanned {count} Mach-O files. Highest minos: {max_v[0]}.{max_v[1]}.{max_v[2]} (from {max_source})")
    if max_v[2] == 0:
        return f"{max_v[0]}.{max_v[1]}"
    return f"{max_v[0]}.{max_v[1]}.{max_v[2]}"


def main():
    if not INFO_PLIST.exists():
        print(f"Info.plist not found: {INFO_PLIST}", file=sys.stderr)
        sys.exit(1)

    version = project_version()
    min_macos = highest_minos()

    with INFO_PLIST.open("rb") as f:
        plist = plistlib.load(f)

    plist["CFBundleShortVersionString"] = version
    plist["CFBundleVersion"] = version
    plist["LSMinimumSystemVersion"] = min_macos

    with INFO_PLIST.open("wb") as f:
        plistlib.dump(plist, f)

    print(f"Patched Info.plist: version={version}, LSMinimumSystemVersion={min_macos}")


if __name__ == "__main__":
    main()
