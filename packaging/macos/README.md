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
   brew install ffmpeg create-dmg imagemagick
   ```
   ffmpeg is needed at *build time* so PyInstaller can find the libav* dylibs to
   bundle. The ffmpeg binary itself is not used at runtime — torchcodec calls libav*
   in-process via Python bindings. See "Why we don't bundle the ffmpeg binary" below.

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
silently rely on anything from your dev machine that won't exist on a user's.
The single most decisive test simulates a clean Mac without Homebrew or any
cached model weights:

```
# 1. Move Homebrew out of the way. Your shell PATH will lose python3, gh,
#    ffmpeg, etc. — that's the point. Use absolute paths (/usr/bin/open) for
#    anything you need to invoke.
sudo mv /opt/homebrew /opt/homebrew.disabled

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

# 6. Restore Homebrew. DON'T FORGET.
sudo mv /opt/homebrew.disabled /opt/homebrew
```

If the .app launches and runs end-to-end with `/opt/homebrew` gone and the
torch cache empty, it has no hidden dev-machine dependencies. The `verify_bundle.py`
build-time check should catch most issues earlier, but this is the only test
that catches "library X was findable on my machine but won't be on a user's"
issues that don't show up as @rpath refs.

A less invasive alternative is to do the same test from a freshly-created
Standard user account on your Mac (System Settings → Users & Groups → Add
User). That account has no shell config, no Homebrew on PATH, and Launch
Services launches apps with the launchd PATH. The downside: more setup, and
`/opt/homebrew` still exists on disk so any unrewritten absolute path
references in the bundle would still resolve (the `mv` test catches those
explicitly).

## Bundling ffmpeg's transitive native deps

`torchcodec` links against ffmpeg's libav* shared libraries (libavutil,
libavformat, libavcodec, libswresample, ...). Those in turn link against codec
libraries like libx264, libx265, libvpx, libaom, libdav1d, etc. PyInstaller's
automatic dependency analysis catches the libav* libraries and most of their
direct deps, but historically misses some transitive ones — for example
`libx265` is referenced via `@rpath/libx265.NNN.dylib` and was silently omitted
from earlier builds, producing an .app that crashed on any user's machine.

The spec works around this by walking `otool -L` recursively from the
Homebrew-installed `libav*`/`libsw*` and bundling every `/opt/homebrew/...`
dylib in the closure. `verify_bundle.py` then fails the build if any
`@rpath/<name>` reference inside the bundle still points at a missing file.

If you ever upgrade Homebrew packages and ffmpeg's link set changes, the spec
auto-discovers the new closure on the next build. No manual list to keep in
sync.

## Why we don't bundle the ffmpeg binary

Earlier versions of the spec bundled `ffmpeg` and `ffprobe` into
`Contents/Frameworks/bin/`. That was removed because:

- demucs has multiple audio backends; the ffmpeg-binary backend is only one of
  them and the torchcodec backend covers everything we need.
- torchcodec uses the **libav* shared libraries** directly via Python bindings —
  it does not invoke the ffmpeg binary as a subprocess.
- PyInstaller's dependency analysis already bundles the libav* dylibs into
  `Contents/Resources/` automatically, because torchcodec links against them.

So the ffmpeg binary was redundant. We do still require ffmpeg to be installed at
build time (via Homebrew) so PyInstaller can find those libav* dylibs.

A `shutil.which("ffmpeg")` check still exists in `app.py` and `cli.py`, but it
runs only when **not frozen** (i.e. dev mode running from source). In dev mode,
torchcodec needs the libav* from `/opt/homebrew/opt/ffmpeg/lib/`, and the check
gives a friendly "install ffmpeg with brew" message if it's missing.

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
