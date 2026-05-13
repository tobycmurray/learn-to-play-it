"""Hash-pin third-party model downloads.

Demucs and beat_this both load model checkpoints via
`torch.hub.load_state_dict_from_url`, which by default trusts whatever the
upstream host serves and deserializes it with full pickle support. We replace
that function with one that:

  1. Refuses to load any filename not in `EXPECTED_HASHES`.
  2. Downloads to the same cache location torch.hub would use.
  3. Verifies the cached file's full SHA-256 against the pinned value
     **before** invoking `torch.load`.

After hash verification, the bytes are byte-identical to what was tested
against, so `weights_only=False` is safe: an attacker who compromises the
upstream model host cannot serve a different file undetected. The trust root
is the SHA-256 dict in this file, which lives in the repo's git history.

To pick up an upstream model upgrade: delete the relevant entry, run the app
to let it re-download, record the new SHA-256, commit. The change is then
reviewable in a diff like any other.


Per-model trust posture
-----------------------

The two models are sourced differently and that shapes how aggressively we
intervene:

* **beat_this (`beat_this-final0.ckpt`)** — re-hosted as a release asset on
  this repo (see learntoplayit/beats.py:BEAT_THIS_CHECKPOINT_URL). Upstream
  ships it from a JKU Nextcloud public share keyed only by the shortname
  "final0"; the filename is *not* content-addressed, so the share owner can
  silently replace the bytes at the same URL, and a single host outage at
  cloud.cp.jku.at would break new installs. Re-hosting collapses the trust
  root to this repo (which we already trust for the code) and removes the
  third-party availability dependency.

* **demucs (`5c90dfd2-34c22ccb.th`)** — left on Meta's CDN
  (dl.fbaipublicfiles.com). The filename embeds an 8-hex-char SHA-256 prefix,
  i.e. it's content-addressed: any change to the model would produce a new
  filename, which would require a new demucs package release, which our
  hash-pinned lockfile pins us away from until you explicitly run
  packaging/update_locks.sh. A "same URL, different bytes" attack is also
  visible to every other demucs user via torch.hub's check_hash=True, so it's
  loud rather than stealthy. The hash pin in EXPECTED_HASHES is sufficient on
  its own. Re-hosting would be defensible on availability grounds (if Meta
  retires the URL) but is deferred — the simpler fix at that point would be
  to bundle the file into the .app rather than maintain a second mirror.
"""
import hashlib
import sys
from pathlib import Path


EXPECTED_HASHES: dict[str, str] = {
    # demucs htdemucs_6s (the model demucs.separate loads for `-n htdemucs_6s`).
    # Source: https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th
    "5c90dfd2-34c22ccb.th":
        "34c22ccb381c6f9fdbf324f04e1e2fe21aaaf293f5ded163a162697ff9a02ddd",

    # beat_this final0 (the checkpoint File2Beats loads for shortname "final0").
    # Source: https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt
    "beat_this-final0.ckpt":
        "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331",
}


_installed = False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def install() -> None:
    global _installed
    if _installed:
        return

    import torch
    import torch.hub

    def _safe(url, model_dir=None, map_location=None, progress=True,
              check_hash=False, file_name=None, weights_only=None, **_):
        if file_name is None:
            file_name = url.rsplit("/", 1)[-1].split("?", 1)[0]

        expected = EXPECTED_HASHES.get(file_name)
        if expected is None:
            raise RuntimeError(
                f"[ltpi.safe_torch] refusing to download unpinned file {file_name!r} "
                f"from {url}. To accept it, add its SHA-256 to "
                f"learntoplayit.safe_torch.EXPECTED_HASHES."
            )

        cache_dir = Path(model_dir) if model_dir else Path(torch.hub.get_dir()) / "checkpoints"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / file_name

        if not cache_path.exists():
            print(f"[ltpi.safe_torch] downloading {url} -> {cache_path}",
                  file=sys.stderr, flush=True)
            torch.hub.download_url_to_file(url, str(cache_path), progress=progress)

        digest = _sha256(cache_path)
        if digest != expected:
            cache_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"[ltpi.safe_torch] SHA-256 mismatch for {file_name}: "
                f"expected {expected}, got {digest}. Cached file deleted; retry will re-download. "
                f"If this persists, the upstream file has changed and "
                f"EXPECTED_HASHES needs review."
            )

        print(f"[ltpi.safe_torch] verified {file_name} (sha256 matches pin)",
              file=sys.stderr, flush=True)
        return torch.load(cache_path, map_location=map_location, weights_only=False)

    torch.hub.load_state_dict_from_url = _safe
    _installed = True
    print("[ltpi.safe_torch] patched torch.hub.load_state_dict_from_url (hash-pinned)",
          file=sys.stderr, flush=True)
