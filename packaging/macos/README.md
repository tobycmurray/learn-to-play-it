# macOS packaging

Scripts for building, signing, notarizing, and packaging the macOS distribution.

## Quick reference

| Script | What it does |
| --- | --- |
| `build_app.sh [--clean]` | PyInstaller → unsigned `dist/Learn To Play It.app` |
| `sign_and_notarize.sh` | Codesign with hardened runtime, submit to Apple notary, staple |
| `make_dmg.sh [--skip-notarize]` | Build `dist/Learn-To-Play-It-{VERSION}.dmg`, then notarize + staple it |
| `release.sh [--clean]` | Runs the three build scripts above end-to-end |
| `publish_release.sh` | Tag the commit, push the tag, attach the dmg to a GitHub release |
| `patch_info_plist.py` | Called by `build_app.sh`. Sets version + `LSMinimumSystemVersion` derived from `pyproject.toml` and the bundled binaries. |
| `verify_bundle.py` | Called by `build_app.sh`. Fails the build if any `@rpath` reference inside the bundle points at a missing file. |

## Workflows

**Cut a release** (most common):
```
# 1. Decide what version this release is. Edit pyproject.toml if you need to bump it.

# 2. Build, sign, notarize, dmg.
packaging/macos/release.sh --clean

# 3. Tag the commit and create the GitHub release.
packaging/macos/publish_release.sh

# 4. Bump pyproject.toml to the next planned version (e.g. 0.2.0 → 0.3.0), commit, push.
```

`publish_release.sh` refuses to run unless: working tree is clean, current branch
is `main`, local main matches `origin/main`, the tag for the current
`pyproject.toml` version doesn't already exist, and the expected dmg artifact
is on disk. So if you forgot a step, it'll tell you.

The version number lives **only** in `pyproject.toml`. `make_dmg.sh` and
`publish_release.sh` both read it from there. Don't try to track it elsewhere.

**Iterate on the .app build** without paying for notarization each time:
```
packaging/macos/build_app.sh --clean
open "dist/Learn To Play It.app"
```

**Iterate on the .dmg layout** (background image position, icon placement):
```
packaging/macos/make_dmg.sh --skip-notarize
open dist/Learn-To-Play-It.dmg
```
Adjust `--icon`, `--window-size`, `--app-drop-link`, or the background image in
`make_dmg.sh`, then re-run.

**Re-notarize an existing build** (e.g. signing identity changed, but bundle didn't):
```
packaging/macos/sign_and_notarize.sh   # for the .app
packaging/macos/make_dmg.sh            # for the dmg
```

**Bump dependencies** (refresh the lockfiles with newer versions from PyPI):
```
packaging/update_locks.sh --upgrade    # bump existing pins to latest
# or
packaging/update_locks.sh              # add/remove deps after editing pyproject.toml
```
Lockfiles (`requirements.lock`, `requirements-gui.lock`) are committed
artifacts pinned by SHA-256, so the build pipeline can use `--require-hashes`.
Review the diff, then commit. CI catches a missed regen after a `pyproject.toml`
edit (red ✗ on the `lockfile-audit` job) but does not block the push.
The script uses `uv pip compile --universal` so lockfiles work cross-platform.

**Bump FFmpeg** (refresh the conda vendor env with newer FFmpeg / transitive deps):
```
packaging/update_ffmpeg.sh --upgrade   # solve fresh from FFMPEG_CONDA_SPEC
# or
packaging/update_ffmpeg.sh             # rebuild env from current lockfile (sanity check)
```
`packaging/macos/ffmpeg-conda-lock.txt` is a committed conda explicit-format
lockfile pinning FFmpeg + every transitive native dep by URL + SHA-256.
`build_app.sh` refuses to proceed if the conda env diverges from this file.
Override the spec for `--upgrade` via `FFMPEG_CONDA_SPEC="ffmpeg=8.2..."`.

## One-time setup on a new Mac

1. **Apple Developer account** with a Developer ID Application certificate. The
   private key must live in this Mac's login keychain. Either:
   - Generate a CSR here and request a new cert from
     https://developer.apple.com/account, or
   - Export the existing identity as a `.p12` from another Mac and import it
     (`security import developer-id.p12 -k ~/Library/Keychains/login.keychain-db`).
2. **Developer ID - G2 intermediate certificate** in the login keychain. Download
   from https://www.apple.com/certificateauthority/ — without it, the Developer ID
   cert shows as untrusted and `security find-identity -v -p codesigning` won't
   list it.
3. **Notarytool credentials** stored under a keychain profile named `ltpi-notary`
   (or override with `NOTARY_PROFILE` env var). Create an app-specific password at
   https://appleid.apple.com → Sign-In and Security, then:
   ```
   xcrun notarytool store-credentials "ltpi-notary" \
     --apple-id "<apple-id>" --team-id "<team-id>" --password "<app-pw>"
   ```
4. **Build dependencies**:
   ```
   brew install create-dmg imagemagick
   pip install pip-audit uv  # pip-audit: publish_release.sh; uv: update_locks.sh
   ```

   Install python.org Python 3.12. The build script currently expects:

   ```
   /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
   ```

   Install Miniforge/Conda. Conda is used only as a source of conda-forge
   FFmpeg dylibs for the packaged app. It is **not** used as the bundled Python
   runtime.

   The build script creates the FFmpeg vendor environment automatically if
   needed, from the committed `packaging/macos/ffmpeg-conda-lock.txt`. Every
   package is pinned by URL + SHA-256; conda validates each archive against
   its hash during install, so a tampered or republished package fails the
   build loudly. To refresh, run `packaging/update_ffmpeg.sh` (see the "Bump
   FFmpeg" workflow above).

   We intentionally do **not** vendor FFmpeg from Homebrew for release builds.
   Homebrew is convenient for development, but its dylibs may be built with the
   host macOS deployment target and can accidentally raise the packaged app's
   minimum macOS version.

Verify everything is in place:
```
security find-identity -v -p codesigning   # should list "Developer ID Application: ..."
xcrun notarytool history --keychain-profile ltpi-notary   # should list past submissions or be empty
```

## Configuration

The signing identity and notarytool profile are configurable via environment
variables; the defaults are baked into the scripts and should usually be left
alone. To override:

```
IDENTITY="Developer ID Application: Other Name (XXXXXXXXXX)" \
NOTARY_PROFILE=other-profile \
  packaging/macos/release.sh
```

The app build script also supports environment overrides such as:

```
PYTHON_ORG=/path/to/python3.12 \
FFMPEG_CONDA_ENV=ltp-ffmpeg \
FFMPEG_CONDA_LOCK=packaging/macos/ffmpeg-conda-lock.txt \
  packaging/macos/build_app.sh --clean
```

The build script installs Python deps from `requirements-gui.lock` and
conda packages from `ffmpeg-conda-lock.txt`, both with hash validation,
and does **not** regenerate either lockfile. To bump deps, see the
"Bump dependencies" and "Bump FFmpeg" workflows above — lockfiles are
committed artifacts.

## Python and FFmpeg sources

The release build deliberately separates Python from FFmpeg:

| Component | Source | Why |
| --- | --- | --- |
| Python runtime | python.org Python 3.12 | Avoids Homebrew/Conda Python deployment-target and `sys.version` quirks |
| Python packages | pip wheels in `.build-venv` | Reproducible from `requirements-gui.lock` |
| FFmpeg dylibs | conda-forge via `ltp-ffmpeg` | Reproducible from `packaging/macos/ffmpeg-conda-lock.txt`; provides low-`minos` shared libraries for `torchcodec` |
| App bundle | PyInstaller | Packages Python runtime, app code, wheels, and native libraries |
| Minimum macOS | computed post-build | Prevents `Info.plist` from understating true binary requirements |

The important rule is: do not vendor FFmpeg from Homebrew for release builds.

## Entitlements

The `.app` is signed with hardened runtime and **no entitlements**. Empirically
verified that no exception is needed for this app — it does not allocate W+X
memory, does not load unsigned third-party dylibs (torch et al. are re-signed by
codesign `--deep`), and does not need DYLD_* env vars.

If a future change requires an entitlement (e.g., switching to a JIT-using torch
op, adding a plugin model, microphone access), create
`packaging/macos/entitlements.plist` with the needed keys. `sign_and_notarize.sh`
auto-detects the file and passes it to codesign. To go back to no entitlements,
delete the file.

## Pre-release test procedure

Before publishing, verify the .app is genuinely self-contained — i.e. it doesn't
silently rely on Homebrew, Miniforge/Conda, cached model weights, or any other
dev-machine state that won't exist on a user's Mac.

The single most decisive test simulates a clean Mac without Homebrew or Conda
or any cached model weights:

```
# 1. Move Homebrew out of the way. Your shell PATH will lose python3, gh,
#    ffmpeg, etc. — that's the point. Use absolute paths (/usr/bin/open) for
#    anything you need to invoke.
sudo mv /opt/homebrew /opt/homebrew.disabled

# 1a. Do likewise with conda:
mv "$HOME/miniforge3" "$HOME/miniforge3.disabled"


# 2. Delete the torch hub cache so the app has to download model weights fresh
#    on first launch. This exercises the HTTPS / certificate code path.
rm -rf ~/.cache/torch/hub

# 3. Open the dmg, drag .app to /Applications (if not already), and launch:
open /Applications/"Learn To Play It.app"

# 4. Inside the app:
#    - Open an audio file you have to hand
#    - Trigger stem separation (downloads demucs model on first run)
#    - Trigger beat detection (downloads beat_this model on first run)
#    Both should succeed end-to-end with progress dialogs visible.

# 5. (Optional but good) Disable network — turn off Wi-Fi — and verify that
#    a fresh model download fails with a clean error dialog rather than a
#    silent crash.

# 6. Restore Homebrew and Conda. DON'T FORGET.
mv "$HOME/miniforge3.disabled" "$HOME/miniforge3"
sudo mv /opt/homebrew.disabled /opt/homebrew
```

If the .app launches and runs end-to-end with `/opt/homebrew` and miniforge3
gone and the torch cache empty, it has no hidden dev-machine dependencies.
The `verify_bundle.py` build-time check should catch most issues earlier, but
this is the only test that catches "library X was findable on my machine but
won't be on a user's" issues that don't show up as @rpath refs.

A less invasive alternative is to do the same test from a freshly-created
Standard user account on your Mac (System Settings → Users & Groups → Add
User). That account has no shell config, no Homebrew on PATH, and Launch
Services launches apps with the launchd PATH. The downside: more setup, and
`/opt/homebrew` still exists on disk so any unrewritten absolute path
references in the bundle would still resolve (the `mv` test catches those
explicitly).

## Bundling ffmpeg's transitive native deps

`torchcodec` links against FFmpeg's `libav*` shared libraries (`libavutil`,
`libavformat`, `libavcodec`, `libswresample`, ...). Those in turn link against
codec and support libraries such as `libx264`, `libx265`, `libvpx`, `libaom`,
`libdav1d`, OpenSSL, zstd, libxml2, and others.

For release builds we intentionally do **not** vendor FFmpeg from Homebrew.
Homebrew is convenient for development, but its dylibs may be built with the
current host macOS deployment target, which can accidentally raise the packaged
app's minimum macOS version.

Instead, the release build uses:

- python.org Python as the bundled Python runtime; and
- a small Conda/Miniforge environment only as the source of conda-forge FFmpeg
  dylibs.

`build_app.sh` sets `FFMPEG_LIB_DIR` to the Conda environment's `lib` directory
before invoking PyInstaller. The spec file then inspects the installed
`torchcodec` binaries to discover which FFmpeg backend variants are present.

`torchcodec` may ship multiple FFmpeg backend variants, for example FFmpeg
4/5/6/7/8 support. The spec selects the newest backend whose required dylibs are
present in `FFMPEG_LIB_DIR`, then recursively walks `otool -L` from those dylibs
and bundles the full vendor-local dependency closure.

The spec deliberately preserves ABI-name dylibs and symlinks such as
`libavdevice.62.dylib`, because `torchcodec` may reference those exact names via
`@rpath`. Collapsing everything to the fully-versioned target file, such as
`libavdevice.62.3.101.dylib`, can leave unresolved `@rpath` references in the
final app.

The spec also filters out unused `torchcodec` backend binaries. For example, if
the Conda vendor environment provides FFmpeg 8 and the spec selects
`torchcodec`'s FFmpeg 8 backend, then older `torchcodec` FFmpeg 4/5/6/7 backend
binaries are omitted from the bundle. This avoids shipping unused binaries that
contain unresolved references to FFmpeg ABI versions we are not bundling.

`verify_bundle.py` fails the build if any `@rpath/<name>` reference inside the
bundle still points at a missing file. `patch_info_plist.py` computes
`LSMinimumSystemVersion` from the actual Mach-O binaries bundled into the app.

If the FFmpeg package in the vendor Conda environment changes, the spec should
auto-discover the matching `torchcodec` backend and its dependency closure on
the next build. The important invariant is that `FFMPEG_LIB_DIR` must point at a
Conda/Miniforge FFmpeg install whose dylibs have an acceptable Mach-O deployment
target.

## Why we don't bundle the ffmpeg binary

Earlier versions of the spec bundled `ffmpeg` and `ffprobe` into
`Contents/Frameworks/bin/`. That was removed because:

- demucs has multiple audio backends; the ffmpeg-binary backend is only one of
  them and the torchcodec backend covers everything we need.
- torchcodec uses the **libav* shared libraries** directly via Python/native
  bindings — it does not invoke the ffmpeg binary as a subprocess.
- The packaged app needs the FFmpeg shared-library set and its dependency
  closure, not the `ffmpeg` command-line executable.

So the ffmpeg binary is redundant in the packaged app.

A `shutil.which("ffmpeg")` check may still exist in `app.py` and `cli.py`, but
it should run only when **not frozen** (i.e. dev mode running from source). In
dev mode, torchcodec needs some FFmpeg installation available on the developer
machine, and the check gives a friendly "install ffmpeg" message if it is
missing.

In frozen/release mode, the app should rely only on bundled shared libraries.

## Minimum macOS version

`build_app.sh` runs `patch_info_plist.py` after PyInstaller, which scans every
bundled Mach-O binary for its `LC_BUILD_VERSION` `minos` and sets the .app's
`LSMinimumSystemVersion` to the highest one found. So the declared minimum
always reflects the most-restrictive bundled library — if you upgrade
PyInstaller, Python, PySide6, torch, etc. and the new versions need a newer
macOS, the .app will declare it automatically. No drift, no risk of shipping a
.app whose Info.plist understates its true requirements.

The script also sets `CFBundleShortVersionString` and `CFBundleVersion` from
`pyproject.toml`, again to keep things consistent.

Current practical notes:

- Apple Silicon implies macOS 11+ as a realistic lower bound.
- Earlier Homebrew Python/FFmpeg builds accidentally raised the floor to macOS 26.
- Switching to python.org Python and conda-forge FFmpeg removed that accidental floor.
- PySide6 6.9.x lowered the Qt/PySide floor.
- Current builds are likely limited by NumPy wheels at macOS 14.0 unless NumPy changes.

## DMG background image

`dmg-background.png` is referenced by `make_dmg.sh`. If absent, the dmg builds
with a plain background and a warning. To regenerate the simple version:

```
magick -size 600x400 xc:'#ececec' \
  -fill '#888' -stroke '#888' -strokewidth 4 \
  -draw "line 215,185 385,185" \
  -draw "line 385,185 370,170" \
  -draw "line 385,185 370,200" \
  -font /System/Library/Fonts/Supplemental/Arial.ttf -pointsize 14 -fill '#666' -stroke none \
  -gravity center -annotate +0+95 "Drag Learn To Play It to Applications" \
  packaging/macos/dmg-background.png
```

Replace with a properly designed background when you have the time. Dimensions
must match `--window-size` in `make_dmg.sh` (currently 600×400).

## Notarization mechanics

- Each `notarytool submit ... --wait` is safe to Ctrl-C; the submission keeps
  running on Apple's servers. Re-attach with `notarytool wait <id>` or check status
  with `notarytool info <id>`.
- Most submissions complete in 5–20 min, but queue depth varies. Occasionally
  hours. Apple's status: https://developer.apple.com/system-status/
- The `.app` and `.dmg` need separate notarization rounds — Gatekeeper checks
  both independently. Stapling embeds the ticket so Gatekeeper can verify offline;
  without it, the user needs network access on first launch.
- Notarization is a static check (signing valid, malware scan clean) — it does
  **not** run the app. An app can pass notarization and still crash at launch if
  it lacks a needed entitlement. Always test the stapled `.app` before shipping.
