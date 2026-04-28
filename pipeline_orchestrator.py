import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Callable
from time import time
from collections import deque
from datetime import datetime

from config import settings
from streaming_stt import create_stt
from streaming_tts import create_tts
from avatar_engine import create_avatar

logger = logging.getLogger("pipeline_orchestrator")

class PipelineState:
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"

class StreamingPipeline:
    def __init__(
        self,
        send_ws_message: Callable,
        interview_context: Dict,
        interview_mode: str = "mock",
    ):
        self._send_ws = send_ws_message
        self._context = interview_context
        self._mode = interview_mode
        self._state = PipelineState.IDLE

        self._stt: Any = None
        self._tts: Any = None
        self._avatar: Any = None

        self._current_user_transcript: List[str] = []
        self._conversation_history: List[Dict] = []
        self._ttfb_start: Optional[float] = None
        self._ttfb_measurements: List[float] = []

        self._speaking_task: Optional[asyncio.Task] = None
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._accumulated_response: List[str] = []

        self._persona: Dict = interview_context.get("persona", {})
        self._knowledge_map: Dict = interview_context.get("knowledge_map", {})

    @property
    def state(self) -> str:
        return self._state

    @property
    def conversation_history(self) -> List[Dict]:
        return self._conversation_history

    async def initialize(self) -> Dict:
        status = {"stt": False, "tts": False, "avatar": False}

        self._stt = create_stt(
            on_partial=self._handle_stt_partial,
            on_final=self._handle_stt_final,
        )
        status["stt"] = await self._stt.connect()

        self._tts = create_tts(on_audio_chunk=self._handle_tts_audio)
        status["tts"] = await self._tts.connect()

        self._avatar = create_avatar(
            on_audio_chunk=self._handle_avatar_audio,
        )
        avatar_result = await self._avatar.create_session()
        status["avatar"] = avatar_result is not None

        mode = "full"
        if not status["avatar"]:
            mode = "audio_only"
        if not status["tts"]:
            mode = "legacy"
        if not status["stt"]:
            mode = "legacy"

        logger.info(f"Pipeline initialized — mode: {mode}, status: {status}")

        self._state = PipelineState.IDLE

        return {
            "pipeline_mode": mode,
            "stt_connected": status["stt"],
            "tts_connected": status["tts"],
            "avatar_connected": status["avatar"],
            "avatar_session": avatar_result,
        }

    async def handle_audio_data(self, audio_data: str):
        if self._state == PipelineState.SPEAKING:
            await self._handle_interruption()

        if self._state != PipelineState.LISTENING:
            self._state = PipelineState.LISTENING

        await self._stt.transcribe_chunk(audio_data)

    async def handle_vad_speech_start(self):
        if self._state == PipelineState.SPEAKING:
            await self._handle_interruption()

        self._state = PipelineState.LISTENING
        self._current_user_transcript = []
        self._ttfb_start = None

        await self._send_ws({
            "type": "vad_state",
            "speaking": True,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def handle_vad_speech_end(self, final_transcript: Optional[str] = None):
        if final_transcript:
            self._current_user_transcript.append(final_transcript)


        full_response = " ".join(self._current_user_transcript).strip()

        if not full_response or len(full_response) < 3:
            self._state = PipelineState.IDLE
            return

        self._ttfb_start = time()
        self._state = PipelineState.PROCESSING

        await self._send_ws({
            "type": "vad_state",
            "speaking": False,
            "processing": True,
            "user_transcript": full_response,
            "timestamp": datetime.utcnow().isoformat(),
        })

        self._conversation_history.append({
            "role": "candidate",
            "content": full_response,
            "timestamp": datetime.utcnow().isoformat(),
        })

        await self._send_ws({
            "type": "transcription_final",
            "role": "user",
            "text": full_response,
        })

        asyncio.create_task(self._run_llm_tts_pipeline(full_response))

    async def _handle_interruption(self):
        logger.info("Interruption detected — flushing TTS and avatar buffers")
        self._state = PipelineState.INTERRUPTED

        if self._speaking_task:
            self._speaking_task.cancel()
            try:
                await self._speaking_task
            except asyncio.CancelledError:
                pass

        await self._tts.interrupt()
        await self._avatar.interrupt()

        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        partial_response = "".join(self._accumulated_response)
        if partial_response:
            self._conversation_history.append({
                "role": "interviewer",
                "content": partial_response,
                "interrupted": True,
                "timestamp": datetime.utcnow().isoformat(),
            })

        self._accumulated_response = []

        await self._send_ws({
            "type": "ai_interrupted",
            "partial_text": partial_response,
            "timestamp": datetime.utcnow().isoformat(),
        })

        self._state = PipelineState.LISTENING

    async def _run_llm_tts_pipeline(self, user_text: str):
        try:
            self._accumulated_response = []
            self._state = PipelineState.PROCESSING

            await self._tts.close()
            self._tts = create_tts(on_audio_chunk=self._handle_tts_audio)
            await self._tts.connect()

            from ai_services import stream_llm_response

            system_prompt = self._build_system_prompt()

            messages = [{"role": "system", "content": system_prompt}]
            for msg in self._conversation_history[-20:]:
                role = "assistant" if msg.get("role") == "interviewer" else "user"
                messages.append({"role": role, "content": msg["content"]})

            token_buffer = []
            first_token = True

            async for token in stream_llm_response(messages):
                if self._state == PipelineState.INTERRUPTED:
                    return

                self._accumulated_response.append(token)
                token_buffer.append(token)

                if first_token and self._ttfb_start:
                    ttfb = (time() - self._ttfb_start) * 1000
                    self._ttfb_measurements.append(ttfb)
                    logger.info(f"Pipeline TTFB (LLM first token): {ttfb:.0f}ms")
                    first_token = False

                await self._send_ws({
                    "type": "ai_token",
                    "token": token,
                })

                joined = "".join(token_buffer)
                if any(p in joined for p in [".", "!", "?", "\n"]):
                    chunk_text = joined
                    token_buffer = []
                    await self._tts.send_text_chunk(chunk_text)

            if token_buffer:
                await self._tts.send_text_chunk("".join(token_buffer))

            await self._tts.flush_and_close_stream()

            full_response = "".join(self._accumulated_response)

            self._conversation_history.append({
                "role": "interviewer",
                "content": full_response,
                "timestamp": datetime.utcnow().isoformat(),
            })

            await self._send_ws({
                "type": "ai_response_complete",
                "text": full_response,
            })

            self._state = PipelineState.SPEAKING

            if self._mode == "practice":
                asyncio.create_task(self._run_parallel_evaluation(user_text, full_response))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"LLM-TTS pipeline error: {e}")
            self._state = PipelineState.IDLE
            await self._send_ws({
                "type": "error",
                "message": "AI response generation failed — please try again",
            })

    async def _run_parallel_evaluation(self, user_text: str, ai_response: str):
        try:
            from ai_services import evaluate_response_realtime

            current_bg = None
            for bg in self._knowledge_map.get("battlegrounds", []):
                if bg.get("current_turns", 0) < bg.get("max_turns", 3):
                    current_bg = bg
                    break

            evaluation = await evaluate_response_realtime(
                question=ai_response,
                response=user_text,
                difficulty_level=self._context.get("strictness_level", "medium"),
                body_language=[],
                battleground_label=current_bg["label"] if current_bg else "",
                interview_mode=self._mode,
            )

            await self._send_ws({
                "type": "evaluation",
                "score": evaluation.get("score", 50),
                "feedback": evaluation.get("feedback", ""),
                "strengths": evaluation.get("strengths", []),
                "improvements": evaluation.get("improvements", []),
            })

            if evaluation.get("improvements"):
                tip = evaluation["improvements"][0]
                await self._send_ws({
                    "type": "dynamic_tooltip",
                    "tip": f"Try to mention: {tip}",
                })

        except Exception as e:
            logger.error(f"Parallel evaluation failed: {e}")

    def _build_system_prompt(self) -> str:
        persona_name = self._persona.get("name", "Dr. Aris")
        persona_style = self._persona.get("communication_style", "professional and direct")
        persona_traits = self._persona.get("personality_traits", [])

        battlegrounds = self._knowledge_map.get("battlegrounds", [])
        current_bg = None
        for bg in battlegrounds:
            if bg.get("current_turns", 0) < bg.get("max_turns", 3):
                current_bg = bg
                break

        topic_context = ""
        if current_bg:
            topic_context = f"\nCurrent interview topic: {current_bg.get('label', 'General')}"
            topic_context += f"\nOpening question for reference: {current_bg.get('opening_question', '')}"

        mode_instructions = ""
        if self._mode == "practice":
            mode_instructions = (
                "\nThis is PRACTICE mode. Be encouraging but honest. "
                "After the candidate responds, ask a thoughtful follow-up "
                "that probes deeper into their answer."
            )
        else:
            mode_instructions = (
                "\nThis is MOCK mode. Conduct a realistic, high-pressure interview. "
                "Be professional but challenging. Do not provide feedback during the interview."
            )

        return (
            f"You are {persona_name}, an expert technical interviewer. "
            f"Your communication style is {persona_style}. "
            f"Traits: {', '.join(persona_traits) if persona_traits else 'professional, thorough'}. "
            f"{topic_context}"
            f"{mode_instructions}"
            f"\nKeep responses concise (2-4 sentences). Ask ONE clear follow-up question. "
            f"Never break character. Never mention that you are an AI."
        )

    async def _handle_stt_partial(self, text: str, confidence: float):
        await self._send_ws({
            "type": "transcription_partial",
            "role": "user",
            "text": text,
            "confidence": confidence,
        })

    async def _handle_stt_final(self, text: str, confidence: float):
        self._current_user_transcript.append(text)
        await self._send_ws({
            "type": "transcription_final",
            "role": "user",
            "text": text,
            "confidence": confidence,
        })

    async def _handle_tts_audio(self, audio_b64: str):
        self._state = PipelineState.SPEAKING

        await self._send_ws({
            "type": "audio_chunk",
            "audio": audio_b64,
        })

        await self._avatar.send_audio_for_lipsync(audio_b64)

    async def _handle_avatar_audio(self, audio_b64: str):
        await self._send_ws({
            "type": "avatar_audio",
            "audio": audio_b64,
        })

    def get_metrics(self) -> Dict:
        avg_ttfb = 0
        if self._ttfb_measurements:
            avg_ttfb = sum(self._ttfb_measurements) / len(self._ttfb_measurements)

        return {
            "avg_ttfb_ms": round(avg_ttfb, 1),
            "total_exchanges": len([m for m in self._conversation_history if m.get("role") == "candidate"]),
            "interruptions": len([m for m in self._conversation_history if m.get("interrupted")]),
            "pipeline_state": self._state,
        }

    async def shutdown(self):
        self._state = PipelineState.IDLE

        if self._speaking_task:
            self._speaking_task.cancel()

        if self._stt:
            await self._stt.close()
        if self._tts:
            await self._tts.close()
        if self._avatar:
            await self._avatar.close()

        logger.info(f"Pipeline shutdown — metrics: {self.get_metrics()}")
