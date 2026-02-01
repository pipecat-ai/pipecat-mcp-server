#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Screen capture processor for Pipecat MCP Server.

This module provides a FrameProcessor that captures screenshots of the screen
or a specific window and injects them into the pipeline as OutputImageRawFrames.

On macOS, uses ScreenCaptureKit for true window-level capture (content not
affected by overlapping windows).
"""

import asyncio
import os
from typing import Optional

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    OutputImageRawFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Environment variable names
ENV_SCREEN_CAPTURE = "PIPECAT_MCP_SERVER_SCREEN_CAPTURE"
ENV_SCREEN_WINDOW = "PIPECAT_MCP_SERVER_SCREEN_WINDOW"


class ScreenCaptureProcessor(FrameProcessor):
    """FrameProcessor that periodically captures screenshots.

    This processor captures the screen (or a specific window) once per second
    and pushes OutputImageRawFrames downstream.

    The processor is only active if the environment variable
    PIPECAT_MCP_SERVER_SCREEN_CAPTURE is set.

    Optionally, PIPECAT_MCP_SERVER_SCREEN_WINDOW can be set to capture
    a specific window by name instead of the entire screen.

    Example:
        export PIPECAT_MCP_SERVER_SCREEN_CAPTURE=1
        export PIPECAT_MCP_SERVER_SCREEN_WINDOW="Firefox"  # Optional

    """

    def __init__(self, monitor: int = 0, capture_interval: float = 1.0):
        """Initialize the screen capture processor.

        Args:
            monitor: The monitor index to capture (default: 0 for primary monitor).
                    Only used when not capturing a specific window.
            capture_interval: Time in seconds between captures (default: 1.0).

        """
        super().__init__(name="screen-capture")
        self._monitor = monitor
        self._capture_interval = capture_interval
        self._capture_task: Optional[asyncio.Task] = None
        self._backend = None

        # Check if screen capture is enabled
        self._enabled = os.getenv(ENV_SCREEN_CAPTURE) is not None

        # Get optional window name
        self._window_name = os.getenv(ENV_SCREEN_WINDOW)

    async def cleanup(self) -> None:
        """Clean up resources when processor is shutting down."""
        await super().cleanup()
        await self._stop_capture_task()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process incoming frames and manage capture task lifecycle.

        Args:
            frame: The frame to process.
            direction: The frame direction (DOWNSTREAM or UPSTREAM).

        """
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._start(frame)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_capture_task()

        await self.push_frame(frame, direction)

    async def _start(self, frame: StartFrame):
        if not self._enabled:
            logger.debug(f"Screen capture disabled. Set {ENV_SCREEN_CAPTURE}=1 to enable.")
            return

        try:
            from .base_capture_backend import get_capture_backend

            self._backend = get_capture_backend()
            await self._backend.start(self._window_name, self._monitor)
        except ImportError as e:
            logger.error(f"Screen capture dependencies not installed: {e}")
            logger.error("Install with: uv pip install pipecat-ai-mcp-server[screen]")
            return
        except RuntimeError as e:
            logger.error(f"Screen capture not supported: {e}")
            return
        except PermissionError as e:
            logger.error(str(e))
            return

        logger.debug("Screen capture processor enabled")
        if self._window_name:
            logger.debug(f"Will capture window: {self._window_name}")
        else:
            logger.debug(f"Will capture monitor {self._monitor}")

        self._create_capture_task()

    def _create_capture_task(self) -> None:
        """Create and start the periodic capture task."""
        if not self._capture_task:
            self._capture_task = self.create_task(self._capture_task_handler())

    async def _stop_capture_task(self) -> None:
        """Stop the periodic capture task and release backend."""
        if self._capture_task:
            await self.cancel_task(self._capture_task)
            self._capture_task = None
        if self._backend:
            await self._backend.stop()
            self._backend = None

    async def _capture_task_handler(self) -> None:
        """Periodically capture screenshots and push them downstream."""
        while True:
            try:
                result = await self._backend.capture()

                if result:
                    rgb_bytes, (width, height) = result
                    frame = OutputImageRawFrame(
                        image=rgb_bytes,
                        size=(width, height),
                        format="RGB",
                    )
                    await self.push_frame(frame)

                await asyncio.sleep(self._capture_interval)
            except PermissionError as e:
                logger.error(str(e))
                break
            except Exception as e:
                logger.error(f"Error in capture task: {e}")
                await asyncio.sleep(self._capture_interval)
