import asyncio
import base64
import io
import logging
from typing import Callable, Optional
from time import time

import soundfile as sf
import numpy as np

from config import settings

logger = logging.getLogger("streaming_tts")

_kokoro_pipeline = None
_kokoro_loaded = False


def _load_kokoro():
    global _kokoro_pipeline, _kokoro_loaded
    if _kokoro_loaded:
        return _kokoro_pipeline
    try:
        from kokoro import KPipeline
        _kokoro_pipeline = KPipeline(lang_code="a")
        _kokoro_loaded = True
        logger.info("Kokoro TTS loaded")
    except Exception:
        logger.exception("Failed to load Kokoro — will fall back to OpenAI TTS")
        _kokoro_loaded = True
    return _kokoro_pipeline


class KokoroTTS:

    def __init__(self, on_audio_chunk: Optional[Callable] = None):
        self._on_audio_chunk = on_audio_chunk
        self._text_buffer: list[str] = []
        self._send_start_time: Optional[float] = None
        self._first_byte_time: Optional[float] = None

    @property
    def available(self) -> bool:
        return _load_kokoro() is not None

    async def connect(self):
        return self.available

    async def send_text_chunk(self, text: str):
        if not self._send_start_time:
            self._send_start_time = time()
        self._text_buffer.append(text)

    async def flush_and_close_stream(self):
        full_text = "".join(self._text_buffer).strip()
        self._text_buffer = []
        if not full_text:
            return

        pipeline = _load_kokoro()
        if not pipeline:
            return

        voice = getattr(settings, "KOKORO_VOICE", "af_heart")
        speed = getattr(settings, "KOKORO_SPEED", 1.0)

        loop = asyncio.get_running_loop()
        audio_b64 = await loop.run_in_executor(
            None, lambda: _generate_audio(pipeline, full_text, voice, speed)
        )

        if audio_b64:
            if not self._first_byte_time and self._send_start_time:
                self._first_byte_time = time()
                ttfb = (self._first_byte_time - self._send_start_time) * 1000
                logger.info(f"Kokoro TTS TTFB: {ttfb:.0f}ms")

            if self._on_audio_chunk:
                await self._on_audio_chunk(audio_b64)

    async def interrupt(self):
        self._text_buffer = []
        self._first_byte_time = None
        self._send_start_time = None
        logger.info("Kokoro TTS interrupted")

    async def close(self):
        self._text_buffer = []

    def get_ttfb_ms(self) -> Optional[float]:
        if self._first_byte_time and self._send_start_time:
            return (self._first_byte_time - self._send_start_time) * 1000
        return None


def _generate_audio(pipeline, text: str, voice: str, speed: float) -> Optional[str]:
    try:
        chunks = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            chunks.append(audio)

        if not chunks:
            return None

        full_audio = np.concatenate(chunks)

        buf = io.BytesIO()
        sf.write(buf, full_audio, 24000, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("ascii")

    except Exception:
        logger.exception("Kokoro audio generation failed")
        return None


class FallbackTTS:

    def __init__(self, on_audio_chunk: Optional[Callable] = None):
        self._on_audio_chunk = on_audio_chunk
        self._text_buffer: list[str] = []

    @property
    def available(self) -> bool:
        return bool(settings.OPENAI_API_KEY)

    async def connect(self):
        return self.available

    async def send_text_chunk(self, text: str):
        self._text_buffer.append(text)

    async def flush_and_close_stream(self):
        full_text = "".join(self._text_buffer).strip()
        self._text_buffer = []
        if full_text:
            from ai_services import generate_speech
            audio_b64 = await generate_speech(full_text)
            if audio_b64 and self._on_audio_chunk:
                await self._on_audio_chunk(audio_b64)

    async def interrupt(self):
        self._text_buffer = []
        logger.info("Fallback TTS interrupted")

    async def close(self):
        pass

    def get_ttfb_ms(self):
        return None


def create_tts(on_audio_chunk=None):
    kokoro = KokoroTTS(on_audio_chunk=on_audio_chunk)
    if kokoro.available:
        logger.info("Using Kokoro-82M for TTS")
        return kokoro
    logger.info("Kokoro unavailable — falling back to OpenAI TTS")
    return FallbackTTS(on_audio_chunk=on_audio_chunk)
