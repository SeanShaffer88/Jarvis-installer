"""Non-invasive import hook that patches upstream modules as they load.

Installed from ``sitecustomize.py`` in the generated app root. Upstream files
are not edited, and the macOS implementations remain the ones used on macOS.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from importlib.machinery import PathFinder
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

log = logging.getLogger("jarvis.windows.hook")

PATCHES: dict[str, tuple[str, str]] = {
    "dialog": ("jarvis_win.dialog_win", "apply"),
    "notifier": ("jarvis_win.notifier_win", "apply"),
    "actions": ("jarvis_win.actions_win", "apply"),
    "screen": ("jarvis_win.screen_win", "apply"),
    "preflight": ("jarvis_win.preflight_win", "apply"),
    "session_watch": ("jarvis_win.session_watch_win", "apply"),
    "session_steer": ("jarvis_win.session_steer_win", "apply"),
    "brain": ("jarvis_win.brain_win", "apply_brain"),
    "run_executor": ("jarvis_win.brain_win", "apply_run_executor"),
}

_installed_hook: "JarvisImportHook | None" = None


class PatchingLoader:
    """Delegate to the real loader, then apply a Windows patch in place."""

    def __init__(self, loader: Any, patch_module: str, patch_attr: str):
        self._loader = loader
        self._patch_module = patch_module
        self._patch_attr = patch_attr

    def create_module(self, spec: Any) -> Any:
        create = getattr(self._loader, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module: ModuleType) -> None:
        self._loader.exec_module(module)
        patch_module = importlib.import_module(self._patch_module)
        getattr(patch_module, self._patch_attr)(module)
        module._JARVIS_WINDOWS_PATCHED = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)


class JarvisImportHook:
    def __init__(self, app_root: str | os.PathLike[str], platform: str,
                 patches: dict[str, tuple[str, str]] | None = None):
        self.app_root = Path(app_root).resolve()
        self.platform = platform
        self.patches = dict(patches or PATCHES)

    def find_spec(self, fullname: str, path: Iterable[str] | None = None,
                  target: ModuleType | None = None) -> Any:
        if self.platform != "win32" or fullname not in self.patches:
            return None
        spec = PathFinder.find_spec(fullname, [str(self.app_root)], target)
        if spec is None or spec.loader is None:
            return None
        patch_module, patch_attr = self.patches[fullname]
        spec.loader = PatchingLoader(spec.loader, patch_module, patch_attr)
        return spec


def _apply_to_loaded(modules: dict[str, ModuleType], patches: dict[str, tuple[str, str]]) -> None:
    for name, (patch_module_name, patch_attr) in patches.items():
        module = modules.get(name)
        if module is None or getattr(module, "_JARVIS_WINDOWS_PATCHED", False):
            continue
        patch_module = importlib.import_module(patch_module_name)
        getattr(patch_module, patch_attr)(module)
        module._JARVIS_WINDOWS_PATCHED = True


def install(app_root: str | os.PathLike[str] | None = None, *,
            platform: str | None = None,
            meta_path: list[Any] | None = None,
            modules: dict[str, ModuleType] | None = None) -> JarvisImportHook | None:
    """Install the hook once. Returns None when the overlay is disabled."""
    global _installed_hook
    active_platform = platform or sys.platform
    if active_platform != "win32" or os.getenv("JARVIS_WINDOWS_OVERLAY", "1") == "0":
        return None
    if _installed_hook is not None and meta_path is None:
        return _installed_hook
    root = Path(app_root or os.getenv("JARVIS_APP_ROOT")
                or Path(__file__).resolve().parent.parent)
    hook = JarvisImportHook(root, active_platform)
    target_meta = sys.meta_path if meta_path is None else meta_path
    target_meta.insert(0, hook)
    _apply_to_loaded(sys.modules if modules is None else modules, hook.patches)
    if meta_path is None:
        _installed_hook = hook
    return hook


def uninstall(meta_path: list[Any] | None = None) -> None:
    global _installed_hook
    target_meta = sys.meta_path if meta_path is None else meta_path
    target_meta[:] = [entry for entry in target_meta
                      if not isinstance(entry, JarvisImportHook)]
    if meta_path is None:
        _installed_hook = None


def reset_for_tests() -> None:
    """Test helper: clear the singleton without touching a caller's list."""
    global _installed_hook
    _installed_hook = None
