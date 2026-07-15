# ============================================================================
# MODULE: streaming_tts.py
# PURPOSE: Kokoro TTS pipeline wrapper — async generator yielding base64 WAV
#          chunks for WebSocket streaming during interview turns.
# STRUCTURE:
#   - _load_kokoro_pipeline_for_voice lazy loader
#   - chunked synthesis helpers + async generator (later in file)
# ENDPOINTS: none (used by interview.py inside the WS audio loop)
# DEPENDS ON: config, kokoro, soundfile, numpy
# CONSUMED BY: interview.py (and ai_services for non-streaming TTS fallback)
# DATA TABLES: none
# ============================================================================

import asyncio
import base64
import io
import logging
import threading
from typing import Callable, Optional
from time import time

import soundfile as sf
import numpy as np

from config import settings

logger = logging.getLogger("streaming_tts")

_kokoro_pipelines = {}
_kokoro_pipeline_lock = threading.Lock()
_kokoro_synthesis_locks = {}


def _load_kokoro_pipeline_for_voice(voice: str):
    lang_code = voice[0] if (voice and len(voice) >= 1) else "a"
    if lang_code in _kokoro_pipelines:
        return _kokoro_pipelines[lang_code]
    # Startup warmup and an early interview connection can otherwise load the
    # same 82M model twice. The second caller waits for the single warm model.
    with _kokoro_pipeline_lock:
        if lang_code in _kokoro_pipelines:
            return _kokoro_pipelines[lang_code]
        try:
            from kokoro import KPipeline
            pipeline = KPipeline(lang_code=lang_code)
            _kokoro_pipelines[lang_code] = pipeline
            _kokoro_synthesis_locks[lang_code] = threading.Lock()
            logger.info("Kokoro pipeline loaded for lang_code: %s", lang_code)
            return pipeline
        except Exception as e:
            logger.error("Failed to load Kokoro for lang_code %s: %s", lang_code, e)
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



def _synthesize_blocking(text: str, voice: str, speed: float) -> Optional[str]:
    pipeline = _load_kokoro_pipeline_for_voice(voice)
    if not pipeline:
        return None
    lang_code = voice[0] if (voice and len(voice) >= 1) else "a"
    synthesis_lock = _kokoro_synthesis_locks.setdefault(lang_code, threading.Lock())
    with synthesis_lock:
        return _generate_audio(pipeline, text, voice, speed)



async def synthesize_text_to_base64(text: str) -> Optional[str]:
    voice = getattr(settings, "KOKORO_VOICE", "af_heart")
    speed = getattr(settings, "KOKORO_SPEED", 1.0)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: _synthesize_blocking(text, voice, speed)
    )


async def prewarm_speech_pipeline() -> None:
    """Load Kokoro and execute one tiny inference before an interview starts."""
    started = time()
    try:
        audio = await synthesize_text_to_base64("Hello.")
        if audio:
            logger.info("Kokoro speech pipeline prewarmed in %.2fs", time() - started)
        else:
            logger.warning("Kokoro speech pipeline prewarm returned no audio")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Kokoro speech pipeline prewarm failed")
