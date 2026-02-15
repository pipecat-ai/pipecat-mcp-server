#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Voxtral Realtime STT service using voxmlx."""

import asyncio
import os
import tempfile
from typing import AsyncGenerator

from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

DEFAULT_MODEL = "mlx-community/Voxtral-Mini-4B-Realtime-6bit"
DEFAULT_DELAY_MS = 480
MS_PER_TOKEN = 80


class VoxtralSTTService(SegmentedSTTService):
    """Voxtral Realtime STT service using voxmlx.

    Provides local speech-to-text using Mistral's Voxtral Realtime 4B model
    via the voxmlx library, optimized for Apple Silicon.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        delay_ms: int = DEFAULT_DELAY_MS,
        language: Language = Language.EN,
        **kwargs,
    ):
        """Initialize the Voxtral STT service.

        Args:
            model: HuggingFace model ID for the Voxtral model.
            temperature: Sampling temperature (0.0 = greedy).
            delay_ms: Transcription delay in ms (multiple of 80). Lower is
                faster but less accurate. 480 recommended, 160 for low latency.
            language: Default language for transcription.
            **kwargs: Additional arguments passed to SegmentedSTTService.

        """
        super().__init__(**kwargs)
        self.set_model_name(model)
        self._temperature = temperature
        self._num_delay_tokens = delay_ms // MS_PER_TOKEN
        self._model = None
        self._sp = None
        self._config = None

        self._settings = {
            "language": language,
            "temperature": self._temperature,
        }

    def can_generate_metrics(self) -> bool:
        """Indicate that this service supports metrics."""
        return True

    def _load_model(self):
        """Load the Voxtral model and cache prompt tokens on first use."""
        from voxmlx import _build_prompt_tokens, load_model

        delay_ms = self._num_delay_tokens * MS_PER_TOKEN
        logger.info(f"Loading Voxtral model: {self.model_name} (delay={delay_ms}ms)...")
        self._model, self._sp, self._config = load_model(self.model_name)
        self._prompt_tokens, self._n_delay_tokens = _build_prompt_tokens(
            self._sp, num_delay_tokens=self._num_delay_tokens
        )
        logger.info("Voxtral model loaded")

    def _transcribe(self, audio_path: str) -> str:
        """Run transcription using the cached model.

        Args:
            audio_path: Path to the WAV audio file.

        Returns:
            Transcribed text string.

        """
        from mistral_common.tokens.tokenizers.base import SpecialTokenPolicy
        from voxmlx.generate import generate

        output_tokens = generate(
            self._model,
            audio_path,
            self._prompt_tokens,
            n_delay_tokens=self._n_delay_tokens,
            temperature=self._temperature,
            eos_token_id=self._sp.eos_id,
        )

        return self._sp.decode(output_tokens, special_token_policy=SpecialTokenPolicy.IGNORE)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Transcribe audio using Voxtral Realtime via voxmlx.

        The audio parameter is WAV-formatted bytes from SegmentedSTTService.
        We write it to a temp file and pass the path to voxmlx.

        Args:
            audio: WAV-formatted audio bytes.

        Yields:
            TranscriptionFrame with the transcribed text, or ErrorFrame on failure.

        """
        temp_path = None
        try:
            await self.start_processing_metrics()

            if self._model is None:
                await asyncio.to_thread(self._load_model)

            # Write WAV to temp file for voxmlx
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio)
                temp_path = f.name

            text = await asyncio.to_thread(self._transcribe, temp_path)
            text = text.strip() if text else ""

            await self.stop_processing_metrics()

            if text:
                logger.debug(f"Voxtral transcription: [{text}]")
                yield TranscriptionFrame(
                    text,
                    self._user_id,
                    time_now_iso8601(),
                    self._settings["language"],
                )

        except Exception as e:
            await self.stop_processing_metrics()
            yield ErrorFrame(error=f"Voxtral STT error: {e}")
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
