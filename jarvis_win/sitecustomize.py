"""Template copied to the app root by tools.build_package.py.

Python imports sitecustomize automatically. Starting the server with
PYTHONPATH=<app root> and JARVIS_WINDOWS_OVERLAY=1 makes this the only
installation seam: upstream source stays untouched.
"""

from jarvis_win.hook import install

install()
