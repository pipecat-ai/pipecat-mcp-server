#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Kokoro TTS service implementation."""

import asyncio
from typing import AsyncGenerator, AsyncIterator

import numpy as np
from kokoro import KPipeline
from loguru import logger
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts


class KokoroTTSService(TTSService):
    """Kokoro TTS service implementation.

    Provides local text-to-speech synthesis using the Kokoro-82M model.
    Automatically downloads the model on first use.
    """

    def __init__(
        self,
        *,
        voice_id: str,
        lang_code: str = "a",
        repo_id="hexgrad/Kokoro-82M",
        **kwargs,
    ):
        super().__init__(**kwargs)

        self._voice_id = voice_id
        self._lang_code = lang_code
        self._pipeline = KPipeline(lang_code=self._lang_code, repo_id=repo_id)

        self._resampler = create_stream_resampler()

    def can_generate_metrics(self) -> bool:
        return True

    @traced_tts
    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"{self}: Generating TTS [{text}]")

        def async_next(it):
            try:
                return next(it)
            except StopIteration:
                return None

        async def async_iterator(iterator) -> AsyncIterator[bytes]:
            while True:
                item = await asyncio.to_thread(async_next, iterator)
                if item is None:
                    return

                (_, _, audio) = item

                # Kokoro outputs a PyTorch tensor at 24kHz, convert to int16 bytes
                audio_np = np.array(audio)
                audio_int16 = (audio_np * 32767).astype(np.int16).tobytes()
                audio_data = await self._resampler.resample(audio_int16, 24000, self.sample_rate)

                yield audio_data

        try:
            await self.start_ttfb_metrics()
            await self.start_tts_usage_metrics(text)
            yield TTSStartedFrame()

            async for data in async_iterator(self._pipeline(text, voice=self._voice_id)):
                await self.stop_ttfb_metrics()
                yield TTSAudioRawFrame(audio=data, sample_rate=self.sample_rate, num_channels=1)
        except Exception as e:
            logger.error(f"{self} exception: {e}")
            yield ErrorFrame(error=f"Unknown error occurred: {e}")
        finally:
            logger.debug(f"{self}: Finished TTS [{text}]")
            await self.stop_ttfb_metrics()
            yield TTSStoppedFrame()
