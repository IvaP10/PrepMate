from fastapi import WebSocket
from typing import Dict, Optional, List
import json
import logging
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger("websocket_manager")

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.interview_sessions: Dict[str, Dict] = {}
        self.connection_metadata: Dict[str, Dict] = {}
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()

        if user_id in self.connection_metadata:
            old_metadata = self.connection_metadata[user_id]
            logger.info(f"Reconnection detected: user_id={user_id}")

            await websocket.send_json({
                "type": "reconnected",
                "message": "Connection restored",
                "session_id": old_metadata.get("session_id"),
                "timestamp": datetime.utcnow().isoformat()
            })

        self.active_connections[user_id] = websocket
        self.connection_metadata[user_id] = {
            "connected_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "reconnection_count": self.connection_metadata.get(user_id, {}).get("reconnection_count", 0) + 1
        }

        self.heartbeat_tasks[user_id] = asyncio.create_task(self._heartbeat(user_id))
        logger.info(f"WebSocket connected: user_id={user_id}")

    async def _heartbeat(self, user_id: str):
        while user_id in self.active_connections:
            try:
                await self.send_json({"type": "heartbeat", "timestamp": datetime.utcnow().isoformat()}, user_id)
                await asyncio.sleep(30)
            except Exception:
                logger.warning(f"Heartbeat failed for {user_id}")
                break

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

        if user_id in self.connection_metadata:
            self.connection_metadata[user_id]["disconnected_at"] = datetime.utcnow()

        if user_id in self.heartbeat_tasks:
            self.heartbeat_tasks[user_id].cancel()
            del self.heartbeat_tasks[user_id]

        logger.info(f"WebSocket disconnected: user_id={user_id}")

    async def send_personal_message(self, message: str, user_id: str):
        if user_id not in self.active_connections:
            logger.warning(f"Cannot send message - user {user_id} not connected")
            return False

        try:
            await self.active_connections[user_id].send_text(message)
            self.connection_metadata[user_id]["last_activity"] = datetime.utcnow()
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {user_id}: {str(e)}")
            self.disconnect(user_id)
            return False

    async def send_json(self, data: dict, user_id: str):
        message = json.dumps(data)
        return await self.send_personal_message(message, user_id)

    def create_session(self, session_id: str, user_id: str, interview_data: dict):
        self.interview_sessions[session_id] = {
            "user_id": user_id,
            "interview_data": interview_data,
            "messages": [],
            "started_at": datetime.utcnow(),
            "current_question_index": 0,
            "time_tracking": {
                "total_elapsed": 0,
                "question_start_time": None,
                "battleground_times": {}
            },
            "interruption_count": 0,
            "clarification_requests": []
        }

        if user_id in self.connection_metadata:
            self.connection_metadata[user_id]["session_id"] = session_id

        logger.info(f"Session created: {session_id} for user {user_id}")

    def get_session(self, session_id: str) -> Optional[Dict]:
        return self.interview_sessions.get(session_id)

    def add_message_to_session(self, session_id: str, message: dict):
        if session_id in self.interview_sessions:
            message["timestamp"] = datetime.utcnow().isoformat()
            self.interview_sessions[session_id]["messages"].append(message)

    def track_question_time(self, session_id: str, question_started: bool = True) -> float:
        if session_id not in self.interview_sessions:
            return 0.0

        session = self.interview_sessions[session_id]

        if question_started:
            session["time_tracking"]["question_start_time"] = datetime.utcnow()
            return 0.0

        if session["time_tracking"]["question_start_time"]:
            elapsed = (datetime.utcnow() - session["time_tracking"]["question_start_time"]).total_seconds()
            session["time_tracking"]["total_elapsed"] += elapsed
            session["time_tracking"]["question_start_time"] = None
            return elapsed

        return 0.0

    def should_allow_clarification(self, session_id: str) -> bool:
        if session_id not in self.interview_sessions:
            return False

        session = self.interview_sessions[session_id]
        return len(session.get("clarification_requests", [])) < 2

    def record_clarification(self, session_id: str, question: str):
        if session_id in self.interview_sessions:
            self.interview_sessions[session_id]["clarification_requests"].append({
                "question": question,
                "timestamp": datetime.utcnow().isoformat()
            })

    def should_end_rambling(self, session_id: str, response_duration: float) -> bool:
        if session_id not in self.interview_sessions:
            return False

        interview_data = self.interview_sessions[session_id]["interview_data"]
        difficulty = interview_data.get("difficulty_level", "medium")

        time_limits = {
            "easy": 180,
            "medium": 150,
            "hard": 120,
            "extreme": 90
        }

        limit = time_limits.get(difficulty, 150)

        if response_duration > limit:
            logger.info(f"Response time ({response_duration}s) exceeded limit ({limit}s) for {difficulty}")
            return True

        return False

    async def send_time_warning(self, session_id: str, user_id: str):
        await self.send_json({
            "type": "time_warning",
            "message": "Please wrap up your answer - try to be more concise"
        }, user_id)

    def end_session(self, session_id: str):
        if session_id in self.interview_sessions:
            session = self.interview_sessions[session_id]
            session["ended_at"] = datetime.utcnow()
            logger.info(f"Session ended: {session_id}, duration: {session['time_tracking']['total_elapsed']}s")
            del self.interview_sessions[session_id]

    def is_user_connected(self, user_id: str) -> bool:
        return user_id in self.active_connections

    def get_active_users_count(self) -> int:
        return len(self.active_connections)

    def get_active_sessions_count(self) -> int:
        return len(self.interview_sessions)

    def cleanup_stale_connections(self):
        stale_users = []
        cutoff = datetime.utcnow() - timedelta(minutes=10)

        for user_id, metadata in self.connection_metadata.items():
            if metadata.get("last_activity", datetime.utcnow()) < cutoff:
                stale_users.append(user_id)

        for user_id in stale_users:
            logger.info(f"Cleaning up stale connection: {user_id}")
            self.disconnect(user_id)
            if user_id in self.connection_metadata:
                del self.connection_metadata[user_id]

    async def broadcast_system_message(self, message: str):
        disconnected = []

        for user_id in list(self.active_connections.keys()):
            success = await self.send_json({
                "type": "system_message",
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            }, user_id)

            if not success:
                disconnected.append(user_id)

        for user_id in disconnected:
            self.disconnect(user_id)

class InterviewFlowController:
    def __init__(self, knowledge_map: Dict, session_id: str):
        self.knowledge_map = knowledge_map
        self.session_id = session_id
        self.current_battleground_index = 0
        self.question_history = []

    def can_ask_clarification(self) -> bool:
        if not self.question_history:
            return True

        current = self.question_history[-1]
        return current.get("clarifications_given", 0) < 1

    def record_clarification(self):
        if self.question_history:
            self.question_history[-1]["clarifications_given"] = self.question_history[-1].get("clarifications_given", 0) + 1

    def should_move_to_next_battleground(self, recent_scores: List[float], time_elapsed: int) -> bool:
        battlegrounds = self.knowledge_map.get("battlegrounds", [])

        if self.current_battleground_index >= len(battlegrounds):
            return False

        current_bg = battlegrounds[self.current_battleground_index]

        from knowledge_map import should_transition
        return should_transition(self.knowledge_map, current_bg["id"], time_elapsed, recent_scores)

    def get_next_question(self, previous_response: Optional[str] = None, previous_score: Optional[float] = None) -> Optional[Dict]:
        from knowledge_map import get_next_battleground, generate_contextual_followup

        battleground = get_next_battleground(self.knowledge_map)

        if not battleground:
            return None

        if battleground["current_turns"] == 0:
            question = battleground["opening_question"]
        else:
            question = generate_contextual_followup(
                battleground["label"],
                battleground["opening_question"],
                previous_response or "",
                self.question_history,
                previous_score or 50
            )

        self.question_history.append({
            "battleground_id": battleground["id"],
            "battleground_label": battleground["label"],
            "question": question,
            "turn_number": battleground["current_turns"] + 1,
            "asked_at": datetime.utcnow().isoformat()
        })

        return {
            "question": question,
            "battleground": battleground["label"],
            "turn": battleground["current_turns"] + 1,
            "max_turns": battleground["max_turns"]
        }