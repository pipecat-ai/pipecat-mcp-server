#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Pipecat MCP Agent for voice I/O over MCP protocol.

This module provides the `PipecatMCPAgent` class that exposes voice input/output
capabilities through MCP tools. It manages a Pipecat pipeline with STT and TTS
services, allowing an MCP client to listen for user speech and speak responses.
"""

import asyncio
import sys
from typing import Any, Optional

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    EndFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.runner.types import (
    DailyRunnerArguments,
    RunnerArguments,
    SmallWebRTCRunnerArguments,
    WebSocketRunnerArguments,
)
from pipecat.runner.utils import create_transport
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.services.whisper.stt import WhisperSTTService, WhisperSTTServiceMLX
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from pipecat_mcp_server.processors.kokoro_tts import KokoroTTSService
from pipecat_mcp_server.processors.screen_capture import ScreenCaptureProcessor
from pipecat_mcp_server.processors.vision import VisionProcessor

load_dotenv(override=True)


class PipecatMCPAgent:
    """Pipecat MCP Agent that exposes voice I/O tools.

    Tools:
    - listen(): Wait for user speech and return transcription
    - speak(text): Speak text to the user via TTS
    """

    # Sentinel value to indicate client disconnection
    _DISCONNECT_SENTINEL = object()

    def __init__(
        self,
        transport: BaseTransport,
        runner_args: RunnerArguments,
    ):
        """Initialize the Pipecat MCP Agent.

        Args:
            transport: Transport for audio I/O (Daily, Twilio, or WebRTC).
            runner_args: Runner configuration arguments.

        """
        self._transport = transport
        self._runner_args = runner_args

        self._task: Optional[asyncio.Task] = None
        self._pipeline_task: Optional[PipelineTask] = None
        self._pipeline_runner: Optional[PipelineRunner] = None
        self._user_speech_queue: asyncio.Queue[Any] = asyncio.Queue()

        self._started = False

    async def start(self):
        """Start the voice pipeline.

        Initializes STT and TTS services, creates the processing pipeline,
        and starts it in the background. The pipeline remains active until
        `stop()` is called.

        Raises:
            ValueError: If required API keys are missing from environment.

        """
        if self._started:
            return

        logger.info("Starting Pipecat MCP Agent pipeline...")

        # Create services
        stt = self._create_stt_service()
        tts = self._create_tts_service()

        context = LLMContext()
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(
                    stop=[
                        TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())
                    ]
                ),
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            ),
        )

        self._screen_capture = ScreenCaptureProcessor()
        self._vision = VisionProcessor()

        # Create pipeline with parallel branches:
        # - Main branch: audio processing (STT → aggregator → TTS)
        # - Vision branch: saves frames to disk on demand
        pipeline = Pipeline(
            [
                self._transport.input(),
                self._screen_capture,
                ParallelPipeline(
                    [stt, user_aggregator, tts],
                    [self._vision],
                ),
                # Assistant aggregator before the transport, because we want to
                # keep everyting from the client.
                assistant_aggregator,
                self._transport.output(),
            ]
        )

        self._pipeline_task = PipelineTask(
            pipeline,
            cancel_on_idle_timeout=False,
        )

        self._pipeline_runner = PipelineRunner(handle_sigterm=True)

        @self._transport.event_handler("on_client_connected")
        async def on_connected(transport, client):
            logger.info(f"Client connected")

        @self._transport.event_handler("on_client_disconnected")
        async def on_disconnected(transport, client):
            logger.info(f"Client disconnected")
            if not self._pipeline_task:
                return

            if isinstance(self._runner_args, DailyRunnerArguments):
                await self._user_speech_queue.put("I just disconnected, but I might come back.")
            else:
                await self._user_speech_queue.put(self._DISCONNECT_SENTINEL)
                await self._pipeline_task.cancel()

        @user_aggregator.event_handler("on_user_turn_stopped")
        async def on_user_turn_stopped(aggregator, strategy, message: UserTurnStoppedMessage):
            if message.content:
                await self._user_speech_queue.put(message.content)

        # Start pipeline in background
        self._task = asyncio.create_task(self._pipeline_runner.run(self._pipeline_task))

        self._started = True
        logger.info("Pipecat MCP Agent started!")

    async def stop(self):
        """Stop the voice pipeline.

        Sends an `EndFrame` to gracefully shut down the pipeline and waits
        for the background task to complete.
        """
        if not self._started:
            return

        logger.info("Stopping Pipecat MCP agent...")

        if self._pipeline_task:
            await self._pipeline_task.queue_frame(EndFrame())

        if self._task:
            await self._task

        self._started = False
        logger.info("Pipecat MCP Agent stopped")

    async def listen(self) -> str:
        """Wait for user speech and return the transcribed text.

        Blocks until the user completes an utterance (detected via VAD).
        Starts the pipeline automatically if not already running.

        Returns:
            The transcribed text from the user's speech.

        Raises:
            RuntimeError: If the pipeline task is not initialized.

        """
        if not self._started:
            await self.start()

        if not self._pipeline_task:
            raise RuntimeError("Pipecat MCP Agent not initialized")

        text = await self._user_speech_queue.get()

        # Check if this is a disconnect signal
        if text is self._DISCONNECT_SENTINEL:
            raise RuntimeError("I just disconnected, but I might come back.")

        return text

    async def speak(self, text: str):
        """Speak text to the user using text-to-speech.

        Queues LLM response frames to synthesize and play the given text.
        Starts the pipeline automatically if not already running.

        Args:
            text: The text to speak to the user.

        Raises:
            RuntimeError: If the pipeline task is not initialized.

        """
        if not self._started:
            await self.start()

        if not self._pipeline_task:
            raise RuntimeError("Pipecat MCP Agent not initialized")

        await self._pipeline_task.queue_frames(
            [
                LLMFullResponseStartFrame(),
                LLMTextFrame(text=text),
                LLMFullResponseEndFrame(),
            ]
        )

    async def list_windows(self) -> list[dict]:
        """List all open windows via the screen capture backend.

        Returns:
            A list of dicts with title, app_name, and window_id fields.

        """
        windows = await self._screen_capture._backend.list_windows()
        return [
            {"title": w.title, "app_name": w.app_name, "window_id": w.window_id} for w in windows
        ]

    async def screen_capture(self, window_id: Optional[int] = None) -> Optional[int]:
        """Switch screen capture to a different window or full screen.

        Args:
            window_id: Window ID to capture (from list_windows()), or None for full screen.

        Returns:
            The window ID if found, or None if the window was not found or capturing full screen.

        """
        return await self._screen_capture.screen_capture(window_id)

    async def capture_screenshot(self) -> str:
        """Capture a screenshot from the current screen capture stream.

        Saves the next frame to a temporary PNG file. Screen capture
        must already be started via screen_capture().

        Returns:
            The absolute path to the saved image file.

        """
        self._vision.request_capture()
        return await self._vision.get_result()

    def _create_stt_service(self) -> STTService:
        if sys.platform == "darwin":
            return WhisperSTTServiceMLX(model="mlx-community/whisper-large-v3-turbo")
        else:
            return WhisperSTTService(model="Systran/faster-distil-whisper-large-v3")

    def _create_tts_service(self) -> TTSService:
        return KokoroTTSService(voice_id="af_heart")


async def create_agent(runner_args: RunnerArguments) -> PipecatMCPAgent:
    """Create a PipecatMCPAgent with the appropriate transport.

    Args:
        runner_args: Runner configuration specifying transport type and settings.

    Returns:
        A configured `PipecatMCPAgent` instance ready to be started.

    """
    transport_params = {}

    # Create transport based on runner args type
    if isinstance(runner_args, DailyRunnerArguments):
        from pipecat.transports.daily.transport import DailyParams

        transport_params["daily"] = lambda: DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_out_enabled=True,
            audio_in_filter=RNNoiseFilter(),
        )
    elif isinstance(runner_args, SmallWebRTCRunnerArguments):
        transport_params["webrtc"] = lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_out_enabled=True,
            audio_in_filter=RNNoiseFilter(),
        )
    elif isinstance(runner_args, WebSocketRunnerArguments):
        params_callback = lambda: FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_filter=RNNoiseFilter(),
        )
        transport_params["twilio"] = params_callback
        transport_params["telnyx"] = params_callback
        transport_params["plivo"] = params_callback
        transport_params["exotel"] = params_callback

    transport = await create_transport(runner_args, transport_params)
    return PipecatMCPAgent(transport, runner_args)
