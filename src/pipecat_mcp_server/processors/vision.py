#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Vision processor for on-demand screen capture saving.

Saves screen capture frames to disk when a description is requested,
returning the file path so Claude can analyze the image directly.
"""

import asyncio
import tempfile

from loguru import logger
from PIL import Image
from pipecat.frames.frames import Frame, ImageRawFrame, OutputImageRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class VisionProcessor(FrameProcessor):
    """Save screen capture frames to disk on demand.

    When a description is requested via request_description(), saves the
    next OutputImageRawFrame to a temporary file and puts the path in a queue.
    """

    def __init__(self):
        """Initialize the vision processor."""
        super().__init__(name="vision-processor")
        self._capture_requested: bool = False
        self._result_queue: asyncio.Queue[str] = asyncio.Queue()

    def request_capture(self):
        """Request a capture of the next frame."""
        logger.debug("Screen capture requested")
        self._capture_requested = True

    async def get_result(self) -> str:
        """Wait for and return the saved image path."""
        return await self._result_queue.get()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames and save when capture is requested."""

        def save_image(image_frame: ImageRawFrame):
            image = Image.frombytes("RGB", image_frame.size, image_frame.image)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                image.save(f, format="PNG")
                return f.name

        await super().process_frame(frame, direction)

        if isinstance(frame, OutputImageRawFrame) and self._capture_requested:
            self._capture_requested = False

            path = await asyncio.to_thread(save_image, frame)
            logger.debug(f"Screenshot saved: {path}")
            await self._result_queue.put(path)

        await self.push_frame(frame, direction)
