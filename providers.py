from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Optional


class STTProvider(ABC):
    @abstractmethod
    async def transcribe_stream(self, audio_chunks: AsyncIterator[bytes]) -> AsyncIterator[Dict]:
        ...


class TTSProvider(ABC):
    @abstractmethod
    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        ...


class ResumeParserProvider(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> Dict:
        ...


class ProfileEnricherProvider(ABC):
    @abstractmethod
    async def enrich(self, links: Dict[str, Optional[str]]) -> Dict:
        ...


class EvaluatorProvider(ABC):
    @abstractmethod
    async def evaluate_turn(self, turn: Dict) -> Dict:
        ...
