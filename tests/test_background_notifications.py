import asyncio
import json
import sys
from datetime import datetime, timedelta

database_module = sys.modules.get("database")
if database_module is not None:
    database_module.get_db_connection = getattr(database_module, "get_db_connection", lambda: None)
    database_module.return_db_connection = getattr(database_module, "return_db_connection", lambda conn: None)

import background_tasks


class FakeCursor:
    def __init__(self, users, *, max_created_at=None, created_at=None, performance=(None, 0)):
        self.users = users
        self.max_created_at = max_created_at
        self.created_at = created_at
        self.performance = performance
        self.next_response = None
        self.updates = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT u.user_id"):
            self.next_response = self.users
        elif "SELECT MAX(created_at) FROM Interviews" in normalized:
            self.next_response = (self.max_created_at,)
        elif "SELECT date_created FROM UserInfo" in normalized:
            self.next_response = (self.created_at,)
        elif "SELECT AVG(overall_score), COUNT(*)" in normalized:
            self.next_response = self.performance
        elif normalized.startswith("UPDATE UserInfo SET notification_prefs"):
            self.updates.append(params)
            self.next_response = None

    def fetchall(self):
        return self.next_response

    def fetchone(self):
        return self.next_response

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_notification_worker_sends_target_weekly_and_streak_once(monkeypatch):
    today = datetime.now().date()
    target_date = (today + timedelta(days=3)).isoformat()
    prefs = {
        "inactive_reminder_days": None,
        "target_date": target_date,
        "weekly_summary": True,
        "streak_reminder": True,
    }
    cursor = FakeCursor(
        [("user-1", "Ava Patel", "ava@example.com", json.dumps(prefs))],
        max_created_at=datetime.now() - timedelta(days=1),
        performance=(82.5, 4),
    )
    connection = FakeConnection(cursor)
    sent = []

    monkeypatch.setattr(background_tasks, "get_db_connection", lambda: connection)
    monkeypatch.setattr(background_tasks, "return_db_connection", lambda conn: None)
    monkeypatch.setattr(background_tasks, "send_notification_email", lambda to, email: sent.append((to, email.subject)) or True)

    asyncio.run(background_tasks._run_notification_checks())

    assert [subject for _, subject in sent] == [
        "Your interview is coming up",
        "Your weekly InterAI progress summary",
        "Keep your practice streak going",
    ]
    assert connection.committed is True
    assert len(cursor.updates) == 1

    saved_prefs = json.loads(cursor.updates[0][0])
    assert saved_prefs["_sent"]["target_date"] == f"{target_date}:{today.isoformat()}"
    assert saved_prefs["_sent"]["weekly_summary"].startswith(f"{today.isocalendar().year}-W")
    assert saved_prefs["_sent"]["streak_reminder"] == today.isoformat()


def test_notification_worker_does_not_resend_duplicate_daily_or_weekly_notifications(monkeypatch):
    today = datetime.now().date()
    target_date = (today + timedelta(days=2)).isoformat()
    week = today.isocalendar()
    prefs = {
        "target_date": target_date,
        "weekly_summary": True,
        "streak_reminder": True,
        "_sent": {
            "target_date": f"{target_date}:{today.isoformat()}",
            "weekly_summary": f"{week.year}-W{week.week:02d}",
            "streak_reminder": today.isoformat(),
        },
    }
    cursor = FakeCursor(
        [("user-1", "Ava Patel", "ava@example.com", json.dumps(prefs))],
        max_created_at=datetime.now() - timedelta(days=1),
        performance=(82.5, 4),
    )
    connection = FakeConnection(cursor)
    sent = []

    monkeypatch.setattr(background_tasks, "get_db_connection", lambda: connection)
    monkeypatch.setattr(background_tasks, "return_db_connection", lambda conn: None)
    monkeypatch.setattr(background_tasks, "send_notification_email", lambda to, email: sent.append((to, email.subject)) or True)

    asyncio.run(background_tasks._run_notification_checks())

    assert sent == []
    assert cursor.updates == []
    assert connection.committed is True


def test_notification_worker_uses_account_creation_for_inactivity_fallback(monkeypatch):
    today = datetime.now().date()
    prefs = {"inactive_reminder_days": 7}
    cursor = FakeCursor(
        [("user-1", "Ava Patel", "ava@example.com", json.dumps(prefs))],
        max_created_at=None,
        created_at=datetime.now() - timedelta(days=9),
    )
    connection = FakeConnection(cursor)
    sent = []

    monkeypatch.setattr(background_tasks, "get_db_connection", lambda: connection)
    monkeypatch.setattr(background_tasks, "return_db_connection", lambda conn: None)
    monkeypatch.setattr(background_tasks, "send_notification_email", lambda to, email: sent.append((to, email.subject)) or True)

    asyncio.run(background_tasks._run_notification_checks())

    assert sent == [("ava@example.com", "Time for another practice round?")]
    saved_prefs = json.loads(cursor.updates[0][0])
    assert saved_prefs["_sent"]["inactivity"] == today.isoformat()
