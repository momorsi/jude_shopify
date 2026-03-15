"""
SSL Certificate utility for PyInstaller compatibility.

When running as a PyInstaller executable, the certifi CA bundle is extracted
to a temp directory (_MEIPASS) that Windows may clean up while the app is running.
This module copies the CA bundle to a stable location next to the executable
and provides an SSL context that all HTTPS clients should use.
"""

import ssl
import sys
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ssl_context: ssl.SSLContext = None
_cert_path: str = None


def init_ssl():
    """
    Initialize the stable SSL certificate bundle.
    Call once at application startup before any HTTPS requests.
    """
    global _ssl_context, _cert_path

    try:
        import certifi
        original_cert = certifi.where()
    except ImportError:
        logger.warning("certifi not installed, using system default SSL")
        _ssl_context = ssl.create_default_context()
        return

    if getattr(sys, 'frozen', False):
        # Running as PyInstaller exe: copy cert to a stable location
        exe_dir = Path(sys.executable).parent
        stable_cert = exe_dir / "data" / "cacert.pem"
        stable_cert.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(original_cert, stable_cert)
            _cert_path = str(stable_cert)
            logger.info(f"SSL cert bundle copied to stable location: {_cert_path}")
        except Exception as e:
            logger.warning(f"Failed to copy cert bundle: {e}, using original")
            _cert_path = original_cert
    else:
        # Running from source: use certifi directly
        _cert_path = original_cert

    _ssl_context = ssl.create_default_context(cafile=_cert_path)


def get_ssl_context() -> ssl.SSLContext:
    """Get the SSL context for HTTPS connections to Shopify."""
    if _ssl_context is None:
        init_ssl()
    return _ssl_context


def get_cert_path() -> str:
    """Get the path to the CA bundle file."""
    if _cert_path is None:
        init_ssl()
    return _cert_path
