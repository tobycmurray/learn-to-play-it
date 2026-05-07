"""PyInstaller entry point for the macOS GUI app."""
import os
import sys


def _setup_ssl_certs() -> None:
    """Point Python's ssl module at certifi's CA bundle when running frozen.

    macOS keeps trusted root certs in the Keychain, not on disk. Homebrew's
    Python installer wires the ssl module to find them; the bundled interpreter
    doesn't get that hook, so HTTPS verification fails with 'unable to get
    local issuer certificate' (e.g. when torch.hub downloads model weights).
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        import certifi
    except ImportError:
        return
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


_setup_ssl_certs()


from learntoplayit.app import main


if __name__ == "__main__":
    main()
