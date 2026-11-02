"""Windows screen sight with Pillow and ctypes window enumeration.

One display per call, no screenshot on disk, no subprocess, and no `sips`.
A blank frame is still refused rather than described confidently.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Any, Callable

from . import win32

log = logging.getLogger("jarvis.windows.screen")

_PIL_FACTORY: Callable[[], tuple[Any, Any]] | None = None
_MONITOR_RECTS: Callable[[], list[tuple[int, int, int, int]]] = win32.monitor_rects
_IGNORED_TITLES = frozenset({"Program Manager", "Default IME", "MSCTFIME UI",
                             "Windows Input Experience"})


def _pil(error_cls: type[Exception]) -> tuple[Any, Any]:
    if _PIL_FACTORY is not None:
        return _PIL_FACTORY()
    try:
        from PIL import Image, ImageGrab  # type: ignore[import-not-found]
    except Exception as e:
        raise error_cls("Pillow is not installed, sir, so I can't see your screen") from e
    return Image, ImageGrab


def _resample(image_module: Any) -> Any:
    resampling = getattr(image_module, "Resampling", image_module)
    return getattr(resampling, "LANCZOS", getattr(image_module, "LANCZOS", 1))


def _grab_png(display: int | None, module: Any) -> Any:
    if module.screen_recording_granted() is False:
        raise module.ScreenError(module._NO_PERMISSION)
    Image, ImageGrab = _pil(module.ScreenError)
    grab_kwargs: dict[str, Any] = {}
    if display is not None:
        try:
            index = int(display)
        except (TypeError, ValueError):
            raise module.ScreenError("I couldn't get a picture of that display, sir")
        rects = list(_MONITOR_RECTS())
        if index < 1 or index > len(rects):
            raise module.ScreenError("I couldn't get a picture of that display, sir")
        grab_kwargs = {"bbox": rects[index - 1], "all_screens": True}
    try:
        image = ImageGrab.grab(**grab_kwargs)
    except Exception as e:
        log.warning("ImageGrab failed: %s", e)
        raise module.ScreenError("I couldn't get a picture of your screen, sir")
    if image is None:
        raise module.ScreenError("I couldn't get a picture of your screen, sir")
    image = image.convert("RGB")
    edge = int(module.SHOT_MAX_EDGE)
    if max(image.size) > edge:
        image.thumbnail((edge, edge), _resample(Image))
    sample_edge = int(module.BLANK_SAMPLE_EDGE)
    sample = image.resize((sample_edge, sample_edge), _resample(Image))
    if module._is_blank(list(sample.getdata())):
        raise module.ScreenError(
            "your screen came back blank, sir — which usually means the capture "
            "did not reach the desktop")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    png = buffer.getvalue()
    if len(png) > int(module.MAX_SHOT_BYTES):
        raise module.ScreenError("that picture came out far too large to send, sir")
    return module.Shot(png=png, width=int(image.width), height=int(image.height))


def _blank_file(path: Path, module: Any) -> bool:
    try:
        Image, _ = _pil(module.ScreenError)
        with Image.open(path) as source:
            edge = int(module.BLANK_SAMPLE_EDGE)
            sample = source.convert("RGB").resize((edge, edge), _resample(Image))
            return bool(module._is_blank(list(sample.getdata())))
    except OSError:
        return False
    except module.ScreenError:
        return False


def apply(module: Any) -> Any:
    def screen_recording_granted() -> bool | None:
        """Windows has no Screen Recording grant; None means 'probe unavailable'."""
        return None

    async def capture_screen(display: int | None = None) -> Any:
        """A 1280-edge PNG of the main or requested display, with blank-frame refusal."""
        return await asyncio.to_thread(_grab_png, display, module)

    async def frame_is_blank(path: Path, workdir: Path) -> bool:
        del workdir
        return await asyncio.to_thread(_blank_file, Path(path), module)

    async def list_windows() -> list[Any]:
        try:
            infos = await asyncio.to_thread(win32.list_windows)
        except Exception as e:
            log.warning("window enumeration failed: %s", e)
            raise module.ScreenError("I couldn't read what's open, sir")
        infos = [w for w in infos if w.visible and w.title
                 and w.title not in _IGNORED_TITLES]
        infos.sort(key=lambda w: (not w.foreground, w.title.lower()))
        return [module.Window(app=Path(w.process_name).stem or w.process_name,
                              title=w.title, frontmost=w.foreground)
                for w in infos[:int(module.MAX_WINDOWS)]]

    module.screen_recording_granted = screen_recording_granted
    module._frame_is_blank = frame_is_blank
    module.capture_screen = capture_screen
    module.list_windows = list_windows
    module._WINDOWS_SCRIPT = "# Windows: EnumWindows via ctypes, no AppleScript\n"
    module.WINDOWS_IMAGE_BACKEND = "Pillow.ImageGrab"
    return module
