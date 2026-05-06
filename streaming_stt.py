import logging
from typing import Callable, Optional

from config import settings

logger = logging.getLogger("streaming_stt")


class GroqWhisperSTT:

    def __init__(self, on_final: Optional[Callable] = None):
        self._on_final = on_final

    @property
    def available(self) -> bool:
        return bool(settings.GROQ_API_KEY)

    async def connect(self):
        return self.available

    async def transcribe_chunk(self, audio_b64: str):
        from ai_services import transcribe_audio
        text = await transcribe_audio(audio_b64)
        if text and self._on_final:
            await self._on_final(text, 0.9)
        return text

    async def close(self):
        pass
