# ============================================================================
# MODULE: websocket_manager.py
# PURPOSE: In-memory connection registry for live WS interviews.
#          Tracks active sockets, sessions, and manages heartbeats/reconnections.
#          Not persisted — DB writes happen in interview.py.
# STRUCTURE:
#   - ConnectionManager (connect/disconnect/heartbeat/send/cleanup) (lines 24-134)
# ENDPOINTS: none directly (wired into WS handler in interview.py)
# DEPENDS ON: security_utils
# CONSUMED BY: app.py, interview.py
# DATA TABLES: none (in-memory only)
# ============================================================================

from fastapi import WebSocket
from typing import Dict, Optional, List
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from security_utils import stable_hash

logger = logging.getLogger("websocket_manager")

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.interview_sessions: Dict[str, Dict] = {}
        self.connection_metadata: Dict[str, Dict] = {}
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        # Cancel old heartbeat task and close old connection if it exists
        if user_id in self.heartbeat_tasks:
            self.heartbeat_tasks[user_id].cancel()
            del self.heartbeat_tasks[user_id]

        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].close()
            except Exception:
                pass
            del self.active_connections[user_id]

        await websocket.accept()

        if user_id in self.connection_metadata:
            old_metadata = self.connection_metadata[user_id]
            logger.info("Reconnection detected: %s", stable_hash(user_id, "user"))

            await websocket.send_json({
                "type": "reconnected",
                "message": "Connection restored",
                "session_id": old_metadata.get("session_id"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        self.active_connections[user_id] = websocket
        self.connection_metadata[user_id] = {
            "connected_at": datetime.now(timezone.utc),
            "last_activity": datetime.now(timezone.utc),
            "reconnection_count": self.connection_metadata.get(user_id, {}).get("reconnection_count", 0) + 1
        }

        self.heartbeat_tasks[user_id] = asyncio.create_task(self._heartbeat(user_id))
        logger.info("WebSocket connected: %s", stable_hash(user_id, "user"))

    async def _heartbeat(self, user_id: str):
        while user_id in self.active_connections:
            try:
                await self.send_json({"type": "heartbeat", "timestamp": datetime.now(timezone.utc).isoformat()}, user_id)
                await asyncio.sleep(30)
            except Exception:
                logger.warning("Heartbeat failed for %s", stable_hash(user_id, "user"))
                break

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

        if user_id in self.connection_metadata:
            self.connection_metadata[user_id]["disconnected_at"] = datetime.now(timezone.utc)

        if user_id in self.heartbeat_tasks:
            self.heartbeat_tasks[user_id].cancel()
            del self.heartbeat_tasks[user_id]

        logger.info("WebSocket disconnected: %s", stable_hash(user_id, "user"))

    async def send_json(self, data: dict, user_id: str):
        if user_id not in self.active_connections:
            logger.warning("Cannot send message - %s not connected", stable_hash(user_id, "user"))
            return False

        try:
            await self.active_connections[user_id].send_json(data)
            self.connection_metadata[user_id]["last_activity"] = datetime.now(timezone.utc)
            return True
        except Exception as e:
            logger.error("Failed to send message to %s: %s", stable_hash(user_id, "user"), type(e).__name__)
            self.disconnect(user_id)
            return False



    def cleanup_stale_connections(self):
        stale_users = []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

        for user_id, metadata in self.connection_metadata.items():
            if metadata.get("last_activity", datetime.now(timezone.utc)) < cutoff:
                stale_users.append(user_id)

        for user_id in stale_users:
            logger.info("Cleaning up stale connection: %s", stable_hash(user_id, "user"))
            self.disconnect(user_id)
            if user_id in self.connection_metadata:
                del self.connection_metadata[user_id]

        # Clean up lingering, inactive in-memory sessions that were never explicitly ended
        stale_sessions = []
        for session_id, session in list(self.interview_sessions.items()):
            user_id = session.get("user_id")
            if user_id not in self.active_connections:
                metadata = self.connection_metadata.get(user_id)
                if not metadata or metadata.get("last_activity", datetime.now(timezone.utc)) < cutoff:
                    stale_sessions.append(session_id)

        for session_id in stale_sessions:
            logger.info("Cleaning up stale session: %s", stable_hash(session_id, "session"))
            if session_id in self.interview_sessions:
                del self.interview_sessions[session_id]
