from email.mime.multipart import MIMEMultipart

import notification_email
from notification_email import (
    build_inactivity_email,
    build_streak_email,
    build_target_date_email,
    build_weekly_summary_email,
    send_notification_email,
)


def test_notification_templates_include_subject_content_cta_and_text(monkeypatch):
    monkeypatch.setattr(notification_email.settings, "APP_BASE_URL", "https://interai.example")

    emails = [
        build_inactivity_email("Ava Patel", 7),
        build_target_date_email("Ava Patel", "2026-06-09", 7),
        build_weekly_summary_email("Ava Patel", 3, 82.4),
        build_streak_email("Ava Patel"),
    ]

    assert [email.subject for email in emails] == [
        "Time for another practice round?",
        "Your interview is coming up",
        "Your weekly InterAI progress summary",
        "Keep your practice streak going",
    ]
    for email in emails:
        assert "InterAI" in email.html
        assert "https://interai.example" in email.html
        assert "notification settings" in email.html
        assert "https://interai.example" in email.text
        assert email.text.strip()

    assert "7 days since your last practice session" in emails[0].text
    assert "2026-06-09" in emails[1].text
    assert "3 completed interviews" in emails[2].text
    assert "82.4/100" in emails[2].text
    assert "practiced yesterday" in emails[3].text


def test_send_notification_email_uses_smtp_with_html_and_plain_text(monkeypatch):
    sent_messages = []

    class FakeSMTP:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def starttls(self):
            pass

        def login(self, email, password):
            assert email == "sender@example.com"
            assert password == "secret"

        def send_message(self, msg):
            sent_messages.append(msg)

        def quit(self):
            pass

    monkeypatch.setattr(notification_email.settings, "SMTP_EMAIL", "sender@example.com")
    monkeypatch.setattr(notification_email.settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(notification_email.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(notification_email.settings, "SMTP_PORT", 2525)
    monkeypatch.setattr(notification_email.smtplib, "SMTP", FakeSMTP)

    email = build_streak_email("Ava")

    assert send_notification_email("ava@example.com", email) is True
    assert len(sent_messages) == 1

    msg = sent_messages[0]
    assert isinstance(msg, MIMEMultipart)
    assert msg["From"] == "sender@example.com"
    assert msg["To"] == "ava@example.com"
    assert msg["Subject"] == "Keep your practice streak going"
    assert [part.get_content_type() for part in msg.get_payload()] == ["text/plain", "text/html"]


def test_send_notification_email_returns_false_without_smtp_config(monkeypatch):
    monkeypatch.setattr(notification_email.settings, "SMTP_EMAIL", "")
    monkeypatch.setattr(notification_email.settings, "SMTP_PASSWORD", "")

    assert send_notification_email("ava@example.com", build_streak_email("Ava")) is False
