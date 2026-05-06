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
        logger.error("Failed to load Kokoro")
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
                logger.info("Kokoro TTS TTFB: %.0fms", ttfb)

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
        logger.error("Kokoro audio generation failed")
        return None


class UnavailableTTS:
    def __init__(self, on_audio_chunk: Optional[Callable] = None):
        self._on_audio_chunk = on_audio_chunk

    @property
    def available(self) -> bool:
        return False

    async def connect(self):
        return False

    async def send_text_chunk(self, text: str):
        return None

    async def flush_and_close_stream(self):
        return None

    async def interrupt(self):
        logger.info("Kokoro TTS unavailable; interrupt ignored")

    async def close(self):
        return None

    def get_ttfb_ms(self):
        return None


async def synthesize_text_to_base64(text: str) -> Optional[str]:
    pipeline = _load_kokoro()
    if not pipeline:
        return None
    voice = getattr(settings, "KOKORO_VOICE", "af_heart")
    speed = getattr(settings, "KOKORO_SPEED", 1.0)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: _generate_audio(pipeline, text, voice, speed)
    )


def create_tts(on_audio_chunk=None):
    kokoro = KokoroTTS(on_audio_chunk=on_audio_chunk)
    if kokoro.available:
        logger.info("Using Kokoro-82M for TTS")
        return kokoro
    logger.warning("Kokoro unavailable — TTS disabled")
    return UnavailableTTS(on_audio_chunk=on_audio_chunk)
