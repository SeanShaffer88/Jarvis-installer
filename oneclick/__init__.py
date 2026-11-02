"""Source-only one-click Windows bootstrapper for JARVIS.

The modules here are compiled into ``JarvisOneClick.exe`` with PyInstaller on a
Windows build machine. They do not include upstream JARVIS source, secrets,
certificates, databases, or generated executables in Git.
"""

from __future__ import annotations

APP_NAME = "JARVIS One-Click"
EXE_NAME = "JarvisOneClick.exe"
APP_USER_MODEL_ID = "SeanShaffer.Jarvis.Windows"
PORT = 8340
BIND_HOST = "127.0.0.1"
ORIGIN = "https://localhost:8340"
VOICE_URL = "https://localhost:8340/"
DASHBOARD_URL = "https://localhost:8340/dashboard"
HEALTH_URL = "https://localhost:8340/api/health"
ONCLICK_ENV_VAR = "JARVIS_ONECLICK_APP_ROOT"
