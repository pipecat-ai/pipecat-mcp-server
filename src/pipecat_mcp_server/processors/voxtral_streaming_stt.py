#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Streaming Voxtral Realtime STT service using voxmlx incremental encode/decode."""

import asyncio
import queue
import threading
import time
from typing import AsyncGenerator

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

DEFAULT_MODEL = "mlx-community/Voxtral-Mini-4B-Realtime-6bit"
DEFAULT_DELAY_MS = 480
MS_PER_TOKEN = 80

# Sentinel objects for inter-thread signaling
_START_UTTERANCE = object()
_END_UTTERANCE = object()
_RESET = object()
_SHUTDOWN = object()
_EOS = object()

# Constants from voxmlx
_N_LEFT_PAD_TOKENS = 32
_N_RIGHT_PAD_TOKENS = 17
# Max buffered audio before dropping oldest samples (~10s at 16kHz)
_MAX_PENDING_SAMPLES = 16000 * 10
# Background thread poll interval in seconds (matches WebRTC 10ms frame timing)
_POLL_INTERVAL_SEC = 0.01


class VoxtralStreamingSTTService(STTService):
    """Streaming Voxtral Realtime STT using voxmlx incremental encode/decode.

    Unlike VoxtralSTTService (segmented, processes complete utterances), this
    service processes audio frames as they arrive, yielding partial transcriptions
    during speech for lower perceived latency.

    Uses a background thread for MLX operations with two thread-safe queues:
    - audio_in_queue: pipeline -> background thread (audio samples + sentinels)
    - token_out_queue: background thread -> pipeline (token IDs + EOS sentinel)
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
        """Initialize the streaming Voxtral STT service.

        Args:
            model: HuggingFace model ID for the Voxtral model.
            temperature: Sampling temperature (0.0 = greedy).
            delay_ms: Transcription delay in ms (multiple of 80).
            language: Default language for transcription.
            **kwargs: Additional arguments passed to STTService.

        """
        super().__init__(**kwargs)
        self.set_model_name(model)
        self._temperature = temperature
        self._num_delay_tokens = delay_ms // MS_PER_TOKEN
        self._language = language

        # Model artifacts (loaded once)
        self._model = None
        self._sp = None
        self._config = None
        self._t_cond = None
        self._text_embeds = None
        self._prompt_tokens = None
        self._prefix_len = None
        self._n_layers = None
        self._eos_token_id = None

        # Thread communication
        self._audio_in_queue: queue.Queue = queue.Queue()
        self._token_out_queue: queue.Queue = queue.Queue()

        # Thread control
        self._running = False
        self._processing_thread = None

        # Token accumulation (accessed from async side only)
        self._utterance_tokens: list[int] = []

        self._settings = {
            "language": language,
            "temperature": self._temperature,
        }

    def can_generate_metrics(self) -> bool:
        """Indicate that this service supports metrics."""
        return True

    def _load_model(self):
        """Load the Voxtral model and precompute cached tensors."""
        import mlx.core as mx
        from voxmlx import _build_prompt_tokens, load_model

        delay_ms = self._num_delay_tokens * MS_PER_TOKEN
        logger.info(
            f"Loading Voxtral streaming model: {self.model_name} (delay={delay_ms}ms)..."
        )
        self._model, self._sp, self._config = load_model(self.model_name)
        self._prompt_tokens, _ = _build_prompt_tokens(
            self._sp, num_delay_tokens=self._num_delay_tokens
        )
        self._prefix_len = len(self._prompt_tokens)
        self._eos_token_id = self._sp.eos_id
        self._n_layers = len(self._model.language_model.layers)

        # Precompute time conditioning and text embeddings (model-constant)
        self._t_cond = self._model.time_embedding(
            mx.array([self._num_delay_tokens], dtype=mx.float32)
        )
        # Materialize the lazy MLX computation
        mx.eval(self._t_cond)

        prompt_ids = mx.array([self._prompt_tokens])
        self._text_embeds = self._model.language_model.embed(prompt_ids)[0]
        # Materialize the lazy MLX computation
        mx.eval(self._text_embeds)

        logger.info("Voxtral streaming model loaded")

    async def start(self, frame: StartFrame):
        """Start the streaming STT service and background processing thread."""
        await super().start(frame)

        if self._model is None:
            await asyncio.to_thread(self._load_model)

        self._running = True
        self._processing_thread = threading.Thread(
            target=self._streaming_loop, daemon=True, name="voxtral-streaming"
        )
        self._processing_thread.start()
        logger.info("Voxtral streaming STT thread started")

    async def cleanup(self):
        """Stop the background thread and clean up resources."""
        self._running = False
        self._audio_in_queue.put(_SHUTDOWN)
        if self._processing_thread:
            self._processing_thread.join(timeout=5.0)
            self._processing_thread = None
        await super().cleanup()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Not used in streaming mode; audio is processed via background thread."""
        return
        yield  # noqa: F841 - makes this an async generator

    async def process_audio_frame(self, frame, direction: FrameDirection):
        """Feed audio to the background thread and drain decoded tokens."""
        if self._muted:
            return

        if hasattr(frame, "user_id"):
            self._user_id = frame.user_id
        else:
            self._user_id = ""

        if not frame.audio:
            return

        # Convert PCM int16 bytes to float32 samples
        samples = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32768.0
        self._audio_in_queue.put(samples)

        # Drain decoded tokens from the background thread
        await self._drain_token_queue()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Handle frames, adding sentinel signals for VAD and interruption events."""
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._audio_in_queue.put(_START_UTTERANCE)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._audio_in_queue.put(_END_UTTERANCE)
        elif isinstance(frame, InterruptionFrame):
            self._utterance_tokens = []
            self._audio_in_queue.put(_RESET)

    async def _drain_token_queue(self):
        """Pull decoded tokens from the background thread and emit frames."""
        from mistral_common.tokens.tokenizers.base import SpecialTokenPolicy

        while True:
            try:
                item = self._token_out_queue.get_nowait()
            except queue.Empty:
                break

            if item is _EOS:
                # Emit final TranscriptionFrame
                if self._utterance_tokens:
                    full_text = self._sp.decode(
                        self._utterance_tokens,
                        special_token_policy=SpecialTokenPolicy.IGNORE,
                    ).strip()
                    if full_text:
                        logger.debug(f"Voxtral streaming transcription: [{full_text}]")
                        frame = TranscriptionFrame(
                            text=full_text,
                            user_id=self._user_id,
                            timestamp=time_now_iso8601(),
                            language=self._language,
                        )
                        frame.finalized = True
                        await self.push_frame(frame)
                self._utterance_tokens = []
            elif isinstance(item, int):
                # Token ID
                self._utterance_tokens.append(item)

                # Emit InterimTranscriptionFrame on word boundaries
                partial_text = self._sp.decode(
                    self._utterance_tokens,
                    special_token_policy=SpecialTokenPolicy.IGNORE,
                ).strip()
                if partial_text:
                    # Check if the last decoded character is whitespace (word boundary)
                    raw = self._sp.decode(
                        [item], special_token_policy=SpecialTokenPolicy.IGNORE
                    )
                    if raw and raw[-1] in (" ", "\n"):
                        await self.push_frame(
                            InterimTranscriptionFrame(
                                text=partial_text,
                                user_id=self._user_id,
                                timestamp=time_now_iso8601(),
                                language=self._language,
                            )
                        )

    # -- Background thread -------------------------------------------------

    def _streaming_loop(self):
        """Background thread: incremental encode/decode loop.

        Adapted from voxmlx/stream.py. Reads audio from _audio_in_queue,
        runs incremental mel -> encode -> decode, writes tokens to
        _token_out_queue.
        """
        import mlx.core as mx
        from voxmlx.audio import SAMPLES_PER_TOKEN, log_mel_spectrogram_step
        from voxmlx.cache import RotatingKVCache

        # Streaming state
        audio_tail = None
        conv1_tail = None
        conv2_tail = None
        encoder_cache = None
        ds_buf = None
        decoder_cache = None
        y = None

        pending_audio = np.zeros(0, dtype=np.float32)
        audio_embeds = None
        n_audio_samples_fed = 0
        n_total_decoded = 0
        first_cycle = True
        prefilled = False

        sliding_window = 8192

        def sample(logits):
            if self._temperature <= 0:
                return mx.argmax(logits[0, -1:], axis=-1).squeeze()
            return mx.random.categorical(logits[0, -1:] / self._temperature).squeeze()

        def reset_state():
            nonlocal audio_tail, conv1_tail, conv2_tail, encoder_cache, ds_buf
            nonlocal decoder_cache, y, pending_audio, audio_embeds
            nonlocal n_audio_samples_fed, n_total_decoded, first_cycle, prefilled

            # Explicitly release KV caches before clearing references
            if decoder_cache is not None:
                for cache in decoder_cache:
                    cache.keys = None
                    cache.values = None
            if encoder_cache is not None:
                for cache in encoder_cache:
                    cache.keys = None
                    cache.values = None

            audio_tail = None
            conv1_tail = None
            conv2_tail = None
            encoder_cache = None
            ds_buf = None
            decoder_cache = None
            y = None
            pending_audio = np.zeros(0, dtype=np.float32)
            audio_embeds = None
            n_audio_samples_fed = 0
            n_total_decoded = 0
            first_cycle = True
            prefilled = False

            mx.clear_cache()

        def decode_steps(embeds, n_to_decode):
            """Decode n_to_decode positions. Returns (n_consumed, hit_eos)."""
            nonlocal decoder_cache, y

            for i in range(n_to_decode):
                token_embed = self._model.language_model.embed(y.reshape(1, 1))[0, 0]
                step_embed = (embeds[i] + token_embed)[None, None, :]
                logits = self._model.decode(
                    step_embed, self._t_cond, mask=None, cache=decoder_cache
                )
                next_y = sample(logits)
                mx.async_eval(next_y)

                token_id = y.item()
                if token_id == self._eos_token_id:
                    self._token_out_queue.put(_EOS)
                    decoder_cache = None
                    y = None
                    return i, True

                self._token_out_queue.put(token_id)

                if i > 0 and i % 256 == 0:
                    mx.clear_cache()

                y = next_y

            return n_to_decode, False

        while self._running:
            # Drain audio queue
            new_chunks = []
            sentinel = None
            try:
                while True:
                    item = self._audio_in_queue.get_nowait()
                    if item is _SHUTDOWN:
                        return
                    elif item is _START_UTTERANCE:
                        reset_state()
                        sentinel = "start"
                    elif item is _END_UTTERANCE:
                        sentinel = "end"
                    elif item is _RESET:
                        reset_state()
                        sentinel = "reset"
                    elif isinstance(item, np.ndarray):
                        new_chunks.append(item)
            except queue.Empty:
                pass

            if sentinel == "reset":
                continue

            if new_chunks:
                new_audio = np.concatenate(new_chunks)
                pending_audio = np.append(pending_audio, new_audio)
                # Cap pending_audio to prevent unbounded growth
                if len(pending_audio) > _MAX_PENDING_SAMPLES:
                    pending_audio = pending_audio[-_MAX_PENDING_SAMPLES:]

            # Handle end-of-utterance: right-pad and flush
            if sentinel == "end":
                if decoder_cache is not None and y is not None:
                    right_pad = np.zeros(
                        _N_RIGHT_PAD_TOKENS * SAMPLES_PER_TOKEN, dtype=np.float32
                    )
                    flush_chunk = np.concatenate([pending_audio, right_pad])
                    pending_audio = np.zeros(0, dtype=np.float32)

                    mel, audio_tail = log_mel_spectrogram_step(flush_chunk, audio_tail)
                    new_embeds, conv1_tail, conv2_tail, encoder_cache, ds_buf = (
                        self._model.encode_step(
                            mel, conv1_tail, conv2_tail, encoder_cache, ds_buf
                        )
                    )
                    if new_embeds is not None:
                        # Materialize the lazy MLX computation
                        mx.eval(new_embeds)
                        mx.clear_cache()
                        if audio_embeds is not None:
                            audio_embeds = mx.concatenate([audio_embeds, new_embeds])
                        else:
                            audio_embeds = new_embeds

                    if audio_embeds is not None:
                        decode_steps(audio_embeds, audio_embeds.shape[0])
                        audio_embeds = None

                    # Flush last pending token
                    if y is not None:
                        token_id = y.item()
                        if token_id != self._eos_token_id:
                            self._token_out_queue.put(token_id)

                # Always emit EOS to finalize the utterance
                self._token_out_queue.put(_EOS)
                reset_state()
                continue

            # Encode new audio
            if first_cycle and len(pending_audio) >= SAMPLES_PER_TOKEN:
                # First cycle: feed left-pad + available audio
                left_pad = np.zeros(
                    _N_LEFT_PAD_TOKENS * SAMPLES_PER_TOKEN, dtype=np.float32
                )
                n_feed = (len(pending_audio) // SAMPLES_PER_TOKEN) * SAMPLES_PER_TOKEN
                chunk = np.concatenate([left_pad, pending_audio[:n_feed]])
                pending_audio = pending_audio[n_feed:]
                n_audio_samples_fed += n_feed

                mel, audio_tail = log_mel_spectrogram_step(chunk, audio_tail)
                new_embeds, conv1_tail, conv2_tail, encoder_cache, ds_buf = (
                    self._model.encode_step(
                        mel, conv1_tail, conv2_tail, encoder_cache, ds_buf
                    )
                )
                if new_embeds is not None:
                    # Materialize the lazy MLX computation
                    mx.eval(new_embeds)
                    mx.clear_cache()
                    audio_embeds = new_embeds
                first_cycle = False

            elif not first_cycle and len(pending_audio) >= SAMPLES_PER_TOKEN:
                n_feed = (len(pending_audio) // SAMPLES_PER_TOKEN) * SAMPLES_PER_TOKEN
                chunk = pending_audio[:n_feed]
                pending_audio = pending_audio[n_feed:]
                n_audio_samples_fed += n_feed

                mel, audio_tail = log_mel_spectrogram_step(chunk, audio_tail)
                new_embeds, conv1_tail, conv2_tail, encoder_cache, ds_buf = (
                    self._model.encode_step(
                        mel, conv1_tail, conv2_tail, encoder_cache, ds_buf
                    )
                )
                if new_embeds is not None:
                    # Materialize the lazy MLX computation
                    mx.eval(new_embeds)
                    mx.clear_cache()
                    if audio_embeds is not None:
                        audio_embeds = mx.concatenate([audio_embeds, new_embeds])
                    else:
                        audio_embeds = new_embeds

            if audio_embeds is None:
                time.sleep(_POLL_INTERVAL_SEC)
                continue

            # How many undecoded embeddings are safe to decode
            safe_total = _N_LEFT_PAD_TOKENS + n_audio_samples_fed // SAMPLES_PER_TOKEN
            n_decodable = min(audio_embeds.shape[0], safe_total - n_total_decoded)

            if n_decodable <= 0:
                time.sleep(_POLL_INTERVAL_SEC)
                continue

            if not prefilled:
                if n_total_decoded + audio_embeds.shape[0] < self._prefix_len:
                    time.sleep(_POLL_INTERVAL_SEC)
                    continue

                decoder_cache = [
                    RotatingKVCache(sliding_window) for _ in range(self._n_layers)
                ]

                prefix_embeds = self._text_embeds + audio_embeds[: self._prefix_len]
                prefix_embeds = prefix_embeds[None, :, :]

                logits = self._model.decode(
                    prefix_embeds, self._t_cond, "causal", decoder_cache
                )
                # Materialize the lazy MLX computation for logits and KV cache
                mx.eval(
                    logits, *[x for c in decoder_cache for x in (c.keys, c.values)]
                )

                y = sample(logits)
                mx.async_eval(y)

                audio_embeds = audio_embeds[self._prefix_len :]
                n_total_decoded = self._prefix_len
                prefilled = True

                n_decodable = min(
                    audio_embeds.shape[0], safe_total - n_total_decoded
                )

            if n_decodable <= 0:
                time.sleep(_POLL_INTERVAL_SEC)
                continue

            # Decode new positions
            n_consumed, hit_eos = decode_steps(audio_embeds, n_decodable)
            n_total_decoded += n_consumed

            if audio_embeds.shape[0] > n_consumed:
                audio_embeds = audio_embeds[n_consumed:]
            else:
                audio_embeds = None

            if hit_eos:
                reset_state()

            time.sleep(_POLL_INTERVAL_SEC)
