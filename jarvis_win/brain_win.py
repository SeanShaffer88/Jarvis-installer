"""Patch brain and run executor so Windows never spawns a .cmd shim."""

from __future__ import annotations

import functools
from typing import Any

from . import claude_launcher


def _patch_brain(module: Any) -> None:
    brain_cls = module.Brain
    original_init = brain_cls.__init__
    original_command = brain_cls.command

    @functools.wraps(original_init)
    def init(self: Any, config: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, config, *args, **kwargs)
        supplied = getattr(config, "claude_path", None) or getattr(self, "_claude", None)
        native = claude_launcher.resolve_claude(explicit=supplied)
        if native:
            self._claude = native

    @functools.wraps(original_command)
    def command(self: Any) -> list[str]:
        saved = getattr(self, "_claude", "claude")
        # Upstream calls shlex.split(self._claude); Windows paths with spaces
        # or backslashes must never go through it. Swap in a plain token,
        # build the rest of the command unchanged, then replace argv[0].
        self._claude = "claude"
        try:
            argv = list(original_command(self))
        finally:
            self._claude = saved
        return claude_launcher.ensure_native_claude(argv, explicit=saved)

    brain_cls.__init__ = init
    brain_cls.command = command


def _patch_run_executor(module: Any) -> None:
    executor_cls = module.RunExecutor
    original_init = executor_cls.__init__
    original_command = executor_cls._command

    @functools.wraps(original_init)
    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        supplied = getattr(self, "_claude_path", None)
        native = claude_launcher.resolve_claude(explicit=supplied)
        if native:
            self._claude_path = native

    @functools.wraps(original_command)
    def command(self: Any, *args: Any, **kwargs: Any) -> list[str]:
        saved = getattr(self, "_claude_path", "claude")
        self._claude_path = "claude"
        try:
            argv = list(original_command(self, *args, **kwargs))
        finally:
            self._claude_path = saved
        return claude_launcher.ensure_native_claude(argv, explicit=saved)

    executor_cls.__init__ = init
    executor_cls._command = command


def apply_brain(module: Any) -> Any:
    _patch_brain(module)
    module.ClaudeLaunchError = claude_launcher.ClaudeLaunchError
    return module


def apply_run_executor(module: Any) -> Any:
    _patch_run_executor(module)
    module.ClaudeLaunchError = claude_launcher.ClaudeLaunchError
    return module
