"""Windows compatibility overlay for JARVIS.

This package is copied into the root of a local JARVIS payload by
``tools.build_package.py``. It is imported by the generated ``sitecustomize.py``
and patched into upstream modules at runtime; upstream files are never edited.
"""

__version__ = "0.1.0"
APP_USER_MODEL_ID = "SeanShaffer.Jarvis.Windows"
DEFAULT_PORT = 8340
DEFAULT_BIND_HOST = "127.0.0.1"

__all__ = ["APP_USER_MODEL_ID", "DEFAULT_PORT", "DEFAULT_BIND_HOST"]
