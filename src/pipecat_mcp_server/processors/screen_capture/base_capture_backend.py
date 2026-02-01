#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Abstract base class for screen capture backends and factory function."""

import sys
from abc import ABC, abstractmethod
from typing import Optional, Tuple


class BaseCaptureBackend(ABC):
    """Abstract base class for platform-specific screen capture backends."""

    @abstractmethod
    async def start(self, window_name: Optional[str], monitor: int) -> None:
        """Initialize capture for a window or monitor.

        Args:
            window_name: Optional window title to capture (partial match, case-insensitive).
            monitor: Monitor index to capture when window_name is None.

        """

    @abstractmethod
    async def capture(self) -> Optional[Tuple[bytes, Tuple[int, int]]]:
        """Capture a single frame.

        Returns:
            Tuple of (rgb_bytes, (width, height)) or None if capture failed.

        """

    @abstractmethod
    async def stop(self) -> None:
        """Release capture resources."""


def get_capture_backend() -> BaseCaptureBackend:
    """Return the appropriate capture backend for the current platform.

    Returns:
        A platform-specific BaseCaptureBackend instance.

    Raises:
        RuntimeError: If the current platform is not supported.

    """
    if sys.platform == "darwin":
        from .macos_capture_backend import MacOSCaptureBackend

        return MacOSCaptureBackend()

    if sys.platform == "linux":
        from .linux_x11_capture_backend import LinuxX11CaptureBackend

        return LinuxX11CaptureBackend()

    raise RuntimeError(
        f"Screen capture is not supported on platform '{sys.platform}'. "
        "Currently only macOS and Linux (X11) are supported."
    )
