# Security Policy

*The hardening measures described below were introduced in v0.1.7. Earlier
releases were built and signed without these protections.*

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Use GitHub's
[private vulnerability reporting](https://github.com/tobycmurray/learn-to-play-it/security/advisories/new)
for this repo. That opens an encrypted, tracked advisory between you and the
maintainer, with audit history.

This is a single-maintainer project. Response is best-effort, with no formal
SLA. Expect an initial acknowledgement within a week or two; a fix may take
longer depending on severity and on whether it involves an upstream
dependency.

## Scope

**In scope** — vulnerabilities where the bytes we ship are at risk of being
tampered with, malicious, or exploitable:

- A bug in our own code (anything in `learntoplayit/*` or `packaging/*`) that
  could be exploited to execute attacker-controlled code or leak user data.
- A failure of one of the integrity mechanisms listed under "Hardening" below
  (e.g. a hash pin that doesn't actually verify what it claims to).
- Compromise of the release pipeline itself (signing identity, build machine,
  GitHub repo, lockfiles).

**Out of scope** — vulnerabilities that don't affect the bytes we ship, or
that belong to upstream maintainers:

- A CVE in an upstream package (e.g. `numpy`, `torch`, `pyside6`, `ffmpeg`).
  Please open a regular issue linking the CVE — that's a "deps need a bump,"
  not a security incident.
- A CVE in an upstream package that doesn't affect this app's actual usage
  context (for example, a server-side bug in a library we only use as a
  client). Worth noting in an issue, but not a security report.
- Vulnerabilities in the user's macOS, Apple's signing or notarization
  infrastructure, or third-party tools (Homebrew, the user's Python install).

If you're not sure whether something is in scope, err on the side of
reporting it privately — we can always re-route to a regular issue if it
turns out not to be sensitive.

## Install paths covered

This policy covers two supported install paths:

- **Binary `.dmg` / `.app`** of the most recent release from this repo's GitHub Releases. This is the path most
  users take. All of the hardening below applies.
- **Hash-pinned source install** against the **current `main` HEAD** —
  specifically, the install described in the README under "Hash-pinned
  install" (`pip install --require-hashes -r requirements.lock` followed by
  `pip install -e . --no-deps`). A subset of the hardening applies — see
  the per-bullet tags under "Hardening measures" below.

A third install path — `pip install -e .` directly from `pyproject.toml`,
without using the lockfile — exists for development and exploration. The
trust model below does not cover it: that install trusts whatever PyPI is
currently serving rather than what was audited at release time. If you
want supply-chain integrity from source, use the hash-pinned path.

Security claims in this policy apply to the commit it lives in.

## Trust model

The binary (`.dmg` / `.app`) security rests on trust in the following, in order of how directly we depend on each:

- **GitHub** hosts the source, the DMG, the AI model checkpoints
  (e.g., `models-v1` release), and the lockfiles that pin every byte. Compromise
  of this repo or its release artifacts is the most direct vector.
- **Apple** issues the Developer ID Application certificate, runs the
  notarization service, and ships macOS — the root trust anchor for anyone
  installing the .app.
- **The maintainer's macOS**, where the .app is built and signed. The
  Developer ID Application signing key lives in this machine's login
  keychain.
- **The contents of every package pinned in `requirements.lock`,
  `requirements-gui.lock`, and `packaging/macos/ffmpeg-conda-lock.txt`** at
  the moment those lockfiles were generated.

The binary **does not** trust at install or run time:

- PyPI itself — Python deps are hash-pinned in committed lockfiles and
  installed with `pip install --require-hashes`.
- conda-forge — FFmpeg and its native deps are pinned by URL + SHA-256 in
  `packaging/macos/ffmpeg-conda-lock.txt`; conda validates each archive
  against its hash during install.
- Meta's CDN (`dl.fbaipublicfiles.com`) — the demucs checkpoint is verified
  against a SHA-256 pin in `learntoplayit/safe_torch.py` before `torch.load`
  ever runs. An unpinned URL is refused.
- The original JKU host for beat_this — we re-host the checkpoint on this
  repo's GitHub releases and apply the same SHA-256 pin.
- Any third-party CDN.

Each of those upstream registries and hosts was trusted *once*, at
lockfile-generation time, and the result was committed to git. From then on,
the bytes shipped in the `.dmg` / `.app` binary are fixed regardless of what the upstreams do.

For the **hash-pinned source install** path, the trust set is similar but
shifts. Apple's signing infrastructure and the maintainer's macOS leave the
picture — you're building under your own Python interpreter on your own
machine. In their place, the source install additionally trusts:

- Your Python interpreter and `pip` (whatever's on `PATH` — system,
  Homebrew, conda, asdf, etc.).
- Your system package manager and where it sources FFmpeg (Homebrew on
  macOS, apt on Debian/Ubuntu, dnf on Fedora, …).

GitHub, the committed lockfile contents, and the AI model hash pins still
apply.

## Hardening measures

Each measure is tagged with the install paths it applies to: **[both]** for
both supported paths, **[.app]** for the binary release only, and
**[source-hardened]** for the hash-pinned source install only.

- **[both] Hash-pinned AI model checkpoints.** `learntoplayit/safe_torch.py`
  replaces `torch.hub.load_state_dict_from_url` with a wrapper that verifies
  each downloaded file's full SHA-256 against `EXPECTED_HASHES` before
  invoking `torch.load`. Files whose names aren't in the pin dict are
  refused outright. This is in the runtime code path, so it applies
  regardless of how the app was installed.
- **[both] Beat_this checkpoint re-hosted.** Instead of fetching from a
  third-party Nextcloud share, the app downloads from this repo's
  `models-v1` GitHub release. The hash pin still applies.
- **[.app, source-hardened] Hash-pinned Python dependencies.**
  `requirements*.lock` are generated by `uv pip compile --universal
  --generate-hashes`, committed to the repo, and installed with `pip install
  --require-hashes`. Any drift between PyPI and the committed hashes fails
  the install. For source users this requires following the "Hash-pinned
  install" instructions in the README — bare `pip install -e .` does not
  use the lockfile.
- **[.app] Hash-pinned conda native dependencies.**
  `packaging/macos/ffmpeg-conda-lock.txt` is an explicit-format conda
  lockfile pinning FFmpeg and every transitive native dep (libavcodec,
  libx264, OpenSSL, libxml2, …) by URL + SHA-256. `build_app.sh` refuses to
  proceed if the conda env diverges from the lockfile. Source users get
  FFmpeg from their system package manager instead, so this protection
  does not apply to them.
- **[.app] Hardened-runtime code signing.** The .app is signed with Apple's
  `--options runtime` and no entitlements — the most restrictive
  configuration available outside the Mac App Store. No JIT, no library
  validation bypass, no microphone or camera access.
- **[.app] Notarized DMG.** Apple's notary service scans every build before
  distribution; the DMG is stapled so Gatekeeper validates offline on the
  user's Mac.
- **CI vulnerability scanning** (release process, not user-facing).
  `pip-audit` runs against the lockfiles on every push, hard-failing on any
  known CVE. A separate `lockfile-audit` job regenerates the lockfiles and
  fails (red ✗ → notification email) if the committed versions drift from
  `pyproject.toml`.
- **Release-time vuln gate** (release process, not user-facing).
  `packaging/macos/publish_release.sh` re-runs `pip-audit` and refuses to
  publish on any failure.

## Known limitations

These are honest limitations of the current process rather than hidden
issues — they're listed so reporters can calibrate expectations:

- [.app] **The Developer ID Application signing key lives in the maintainer's
  macOS login keychain**, not in dedicated hardware (HSM or smartcard).
  Compromise of the maintainer's Mac would allow signed malware to be
  distributed under this team identity until the cert is revoked.
- [.app] **The build is not bit-for-bit reproducible.** PyInstaller is currently
  installed unpinned (`pip install pyinstaller` with no version constraint
  or hash) and its output depends on host state. A determined attacker who
  replicated the build environment would not necessarily produce an
  identical DMG.
- [.both] **Single maintainer, no formal security-review process.** Code review on
  this project happens informally, as does testing.
- **CI vulnerability scanning depends on public CVE databases.**
  Vulnerabilities disclosed but not yet published to those databases won't
  be flagged.
- **Source installs without the lockfile aren't covered.** Users who run
  `pip install -e .` directly (without `pip install --require-hashes -r
  requirements.lock` first) are trusting PyPI live for every dependency.
  This is supported as a development path but isn't in the trust model
  described above. The README's "Hash-pinned install" instructions are
  the supported source path.
