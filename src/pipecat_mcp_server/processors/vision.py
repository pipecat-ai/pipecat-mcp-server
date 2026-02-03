#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Vision processors for on-demand screen description.

ImageFrameConverter: Converts OutputImageRawFrame to UserImageRawFrame
VisionProcessor: Extends MoondreamService to capture results
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Optional

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    OutputImageRawFrame,
    UserImageRawFrame,
    VisionTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.moondream.vision import MoondreamService

if TYPE_CHECKING:
    from pipecat_mcp_server.processors.vision import VisionProcessor


class ImageFrameConverter(FrameProcessor):
    """Converts OutputImageRawFrame to UserImageRawFrame for vision processing.

    When VisionProcessor has a pending query, converts the next
    OutputImageRawFrame to a UserImageRawFrame with the query as text.
    """

    def __init__(self, vision_processor: "VisionProcessor"):
        """Initialize the converter.

        Args:
            vision_processor: The VisionProcessor to check for pending queries.

        """
        super().__init__(name="image-frame-converter")
        self._vision = vision_processor

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Convert OutputImageRawFrame when there's a pending query.

        Args:
            frame: The frame to process.
            direction: The frame direction.

        """
        await super().process_frame(frame, direction)

        if isinstance(frame, OutputImageRawFrame) and self._vision._pending_query:
            query = self._vision._pending_query
            self._vision._pending_query = None

            logger.debug("Converting frame for vision analysis")

            user_frame = UserImageRawFrame(
                user_id="screen-capture",
                image=frame.image,
                size=frame.size,
                format=frame.format,
                text=query,
            )
            await self.push_frame(user_frame, direction)
        else:
            await self.push_frame(frame, direction)


class VisionProcessor(MoondreamService):
    """Process vision requests on-demand using Moondream.

    Extends MoondreamService to capture results into a queue.
    Use with ImageFrameConverter to handle OutputImageRawFrame conversion.
    """

    def __init__(self):
        """Initialize the vision processor."""
        super().__init__()
        self._pending_query: Optional[str] = None
        self._result_queue: asyncio.Queue[str] = asyncio.Queue()

    def request_description(self, query: str):
        """Request a description of the next frame.

        Args:
            query: The question or prompt about what's on screen.

        """
        logger.debug(f"Vision description requested: {query}")
        self._pending_query = query

    async def get_result(self) -> str:
        """Wait for and return the vision result.

        Returns:
            The description from Moondream.

        """
        return await self._result_queue.get()

    async def run_vision(self, frame: UserImageRawFrame) -> AsyncGenerator[Frame, None]:
        """Run vision analysis and capture the result.

        Args:
            frame: The user image frame to analyze.

        Yields:
            Frames from the parent Moondream service.

        """
        result_parts = []
        async for result_frame in super().run_vision(frame):
            if isinstance(result_frame, VisionTextFrame):
                result_parts.append(result_frame.text)
            yield result_frame

        description = "".join(result_parts) if result_parts else "No description available."
        logger.debug(f"Vision result: {description[:100]}...")
        await self._result_queue.put(description)
