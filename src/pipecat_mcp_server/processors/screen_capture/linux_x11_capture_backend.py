#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Linux X11 screen capture backend using python-xlib."""

import asyncio
from typing import Optional, Tuple

import numpy as np
from loguru import logger

from .base_capture_backend import BaseCaptureBackend

# Lazy references populated by _ensure_xlib()
_display_module = None
_X_module = None
_Xatom_module = None


def _ensure_xlib():
    """Import python-xlib on first use."""
    global _display_module, _X_module, _Xatom_module
    if _display_module is not None:
        return

    import Xlib.X
    import Xlib.Xatom
    import Xlib.display

    _display_module = Xlib.display
    _X_module = Xlib.X
    _Xatom_module = Xlib.Xatom


def _find_window_by_name(display, window_name: str):
    """Find a window by title (partial match, case-insensitive).

    Args:
        display: Xlib Display instance.
        window_name: Window title to search for.

    Returns:
        An Xlib Window object or None.

    """
    search = window_name.lower()
    root = display.screen().root
    net_wm_name = display.intern_atom("_NET_WM_NAME")

    def _is_viewable(win):
        """Return True if the window is InputOutput and mapped (viewable)."""
        try:
            attrs = win.get_attributes()
            return attrs.win_class == _X_module.InputOutput and attrs.map_state == 2
        except Exception:
            return False

    def _match_title(win):
        """Return True if the window title matches the search string."""
        try:
            prop = win.get_full_property(net_wm_name, 0)
            if prop and prop.value:
                title = prop.value
                if isinstance(title, bytes):
                    title = title.decode("utf-8", errors="replace")
                if search in title.lower():
                    return True
        except Exception:
            pass
        try:
            prop = win.get_full_property(_Xatom_module.XA_WM_NAME, 0)
            if prop and prop.value:
                title = prop.value
                if isinstance(title, bytes):
                    title = title.decode("utf-8", errors="replace")
                if search in title.lower():
                    return True
        except Exception:
            pass
        return False

    def _search(win):
        if _match_title(win) and _is_viewable(win):
            return win

        # Recurse into children
        try:
            children = win.query_tree().children
        except Exception:
            return None
        for child in children:
            result = _search(child)
            if result:
                return result
        return None

    return _search(root)


def _capture_x11(display, window) -> Optional[Tuple[bytes, Tuple[int, int]]]:
    """Capture a window's content via XGetImage.

    Args:
        display: Xlib Display instance.
        window: Xlib Window to capture.

    Returns:
        Tuple of (rgb_bytes, (width, height)) or None on failure.

    """
    try:
        geom = window.get_geometry()
        width = geom.width
        height = geom.height
    except Exception as e:
        logger.error(f"Failed to get window geometry: {e}")
        return None

    if width == 0 or height == 0:
        return None

    try:
        raw = window.get_image(0, 0, width, height, _X_module.ZPixmap, 0xFFFFFFFF)
    except Exception as e:
        logger.error(f"XGetImage failed: {e}")
        return None

    # X11 ZPixmap returns BGRA (32-bit depth)
    data = raw.data
    if isinstance(data, str):
        data = data.encode("latin-1")

    arr = np.frombuffer(data, dtype=np.uint8).reshape(-1, 4)
    # BGRA → RGB
    rgb = np.ascontiguousarray(arr[:, [2, 1, 0]]).tobytes()
    return (rgb, (width, height))


class LinuxX11CaptureBackend(BaseCaptureBackend):
    """Linux screen capture backend using X11/Xlib."""

    def __init__(self):
        """Initialize the Linux X11 capture backend."""
        self._display = None
        self._window = None

    async def start(self, window_name: Optional[str], monitor: int) -> None:
        """Set up the X11 display and find the target window.

        Args:
            window_name: Optional window title to capture.
            monitor: Monitor index (used for root window capture).

        """
        _ensure_xlib()

        self._display = _display_module.Display()

        if window_name:
            self._window = _find_window_by_name(self._display, window_name)
            if self._window:
                try:
                    prop = self._window.get_full_property(
                        self._display.intern_atom("_NET_WM_NAME"), 0
                    )
                    title = prop.value if prop else "(unknown)"
                    if isinstance(title, bytes):
                        title = title.decode("utf-8", errors="replace")
                    logger.debug(f"Found window: '{title}'")
                except Exception:
                    logger.debug("Found matching window")
            else:
                logger.warning(f"Window '{window_name}' not found, falling back to full screen")

        if self._window is None:
            self._window = self._display.screen(monitor).root
            logger.debug(f"Capturing root window (screen {monitor})")

    async def capture(self) -> Optional[Tuple[bytes, Tuple[int, int]]]:
        """Capture a single frame from the X11 window.

        Returns:
            Tuple of (rgb_bytes, (width, height)) or None on failure.

        """
        if self._display is None or self._window is None:
            return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _capture_x11, self._display, self._window)

    async def stop(self) -> None:
        """Release X11 resources."""
        if self._display:
            self._display.close()
            self._display = None
        self._window = None
