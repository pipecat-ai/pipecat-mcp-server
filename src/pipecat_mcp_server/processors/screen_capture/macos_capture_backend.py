#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""macOS screen capture backend using ScreenCaptureKit.

All pyobjc imports are deferred to first use to avoid triggering CoreGraphics
initialization at import time, which crashes in non-GUI processes.
"""

import asyncio
from typing import Optional, Tuple

from loguru import logger

from .base_capture_backend import BaseCaptureBackend

# Lazy references populated by _ensure_frameworks()
_Quartz = None
_SCKit = None


def _ensure_frameworks():
    """Import pyobjc frameworks on first use.

    Importing Quartz/ScreenCaptureKit triggers CoreGraphics initialization,
    which must happen after the process has window-server access.
    """
    global _Quartz, _SCKit
    if _Quartz is not None:
        return

    import CoreMedia  # noqa: F401 — needed for CMSampleBuffer bridging
    import Quartz
    import ScreenCaptureKit

    # Force CG initialization so later calls don't hit the assertion
    Quartz.CGMainDisplayID()

    _Quartz = Quartz
    _SCKit = ScreenCaptureKit


def _cgimage_to_rgb(cg_image) -> Optional[Tuple[bytes, Tuple[int, int]]]:
    """Convert a CGImage to RGB bytes.

    Args:
        cg_image: A CGImage reference.

    Returns:
        Tuple of (rgb_bytes, (width, height)) or None on failure.

    """
    import numpy as np

    Q = _Quartz

    width = Q.CGImageGetWidth(cg_image)
    height = Q.CGImageGetHeight(cg_image)

    if width == 0 or height == 0:
        return None

    # Get raw pixel data via CGDataProvider (returns NSData → bytes)
    provider = Q.CGImageGetDataProvider(cg_image)
    ns_data = Q.CGDataProviderCopyData(provider)
    raw = bytes(ns_data)

    bpp = Q.CGImageGetBitsPerPixel(cg_image) // 8
    src_row = Q.CGImageGetBytesPerRow(cg_image)

    # Handle row padding: if bytes_per_row > width * bpp, strip padding per row
    if src_row != width * bpp:
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, src_row)
        arr = arr[:, : width * bpp].reshape(-1, bpp)
    else:
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, bpp)

    # ScreenCaptureKit returns BGRA — swap to RGB
    rgb = np.ascontiguousarray(arr[:, [2, 1, 0]]).tobytes()
    return (rgb, (width, height))


async def _get_shareable_content():
    """Enumerate shareable content (windows and displays).

    Returns:
        An SCShareableContent instance.

    Raises:
        PermissionError: If screen recording permission is denied.

    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    def handler(content, error):
        if error is not None:
            err_str = str(error)
            if "permission" in err_str.lower() or "denied" in err_str.lower():
                loop.call_soon_threadsafe(
                    future.set_exception,
                    PermissionError(
                        "Screen recording permission denied. "
                        "Grant access in System Settings > Privacy & Security > Screen Recording."
                    ),
                )
            else:
                loop.call_soon_threadsafe(
                    future.set_exception,
                    RuntimeError(f"Failed to get shareable content: {error}"),
                )
            return
        loop.call_soon_threadsafe(future.set_result, content)

    _SCKit.SCShareableContent.getShareableContentWithCompletionHandler_(handler)

    return await future


def _make_window_filter(content, window_name: str):
    """Create an SCContentFilter for a specific window.

    Args:
        content: SCShareableContent instance.
        window_name: Window title to search for (partial match, case-insensitive).

    Returns:
        An SCContentFilter or None if no matching window found.

    """
    search = window_name.lower()
    for window in content.windows():
        title = window.title()
        if title and search in title.lower():
            logger.debug(f"Found window: '{title}' (ID: {window.windowID()})")
            return _SCKit.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)

    return None


def _make_display_filter(content, monitor_index: int):
    """Create an SCContentFilter for a display.

    Args:
        content: SCShareableContent instance.
        monitor_index: Index into the displays list.

    Returns:
        An SCContentFilter for the requested display.

    """
    displays = content.displays()
    if monitor_index >= len(displays):
        logger.warning(f"Monitor index {monitor_index} out of range, using primary display")
        monitor_index = 0

    display = displays[monitor_index]
    logger.debug(f"Using display {display.displayID()} (index {monitor_index})")

    # Capture entire display excluding no windows
    f = _SCKit.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, [])
    return f


class MacOSCaptureBackend(BaseCaptureBackend):
    """macOS capture backend using ScreenCaptureKit (macOS 14+).

    Uses SCScreenshotManager for single-frame capture with true window-level
    isolation (content not affected by overlapping windows).
    """

    def __init__(self):
        """Initialize the macOS capture backend."""
        self._filter: Optional[object] = None
        self._config: Optional[object] = None

    async def start(self, window_name: Optional[str], monitor: int) -> None:
        """Set up the ScreenCaptureKit filter and configuration.

        Args:
            window_name: Optional window title to capture.
            monitor: Monitor index when not capturing a specific window.

        """
        _ensure_frameworks()

        content = await _get_shareable_content()

        if window_name:
            self._filter = _make_window_filter(content, window_name)
        if self._filter is None:
            if window_name:
                logger.warning(f"Window '{window_name}' not found, falling back to full screen")
            self._filter = _make_display_filter(content, monitor)

        self._config = _SCKit.SCStreamConfiguration.alloc().init()
        # Capture at screen scale (Retina)
        self._config.setScalesToFit_(True)

    async def capture(self) -> Optional[Tuple[bytes, Tuple[int, int]]]:
        """Capture a single screenshot via SCScreenshotManager.

        Returns:
            Tuple of (rgb_bytes, (width, height)) or None on failure.

        """
        if self._filter is None or self._config is None:
            return None

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def handler(image, error):
            if error is not None:
                err_str = str(error)
                if "permission" in err_str.lower() or "denied" in err_str.lower():
                    loop.call_soon_threadsafe(
                        future.set_exception,
                        PermissionError(
                            "Screen recording permission denied. "
                            "Grant access in System Settings > Privacy & Security > Screen Recording."
                        ),
                    )
                else:
                    loop.call_soon_threadsafe(
                        future.set_exception, RuntimeError(f"SCScreenshotManager error: {error}")
                    )
                return
            loop.call_soon_threadsafe(future.set_result, image)

        _SCKit.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            self._filter, self._config, handler
        )

        try:
            cg_image = await future
        except PermissionError:
            raise
        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")
            return None

        if cg_image is None:
            return None

        return await loop.run_in_executor(None, _cgimage_to_rgb, cg_image)

    async def stop(self) -> None:
        """Release capture resources."""
        self._filter = None
        self._config = None
