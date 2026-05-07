# macOS packaging

Scripts for building, signing, notarizing, and packaging the macOS distribution.

## Quick reference

| Script | What it does |
| --- | --- |
| `build_app.sh [--clean]` | PyInstaller → unsigned `dist/Learn To Play It.app` |
| `sign_and_notarize.sh` | Codesign with hardened runtime, submit to Apple notary, staple |
| `make_dmg.sh [--skip-notarize]` | Build `dist/Learn-To-Play-It.dmg`, then notarize + staple it |
| `release.sh [--clean]` | Runs all three above end-to-end |

## Workflows

**Cut a release** (most common):
```
packaging/macos/release.sh --clean
```
Produces a signed, notarized, stapled `.app` and `.dmg`. Distribute the `.dmg`.

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
