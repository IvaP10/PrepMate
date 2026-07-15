import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Optional

from config import settings
from security_utils import stable_hash

logger = logging.getLogger("notification_email")


@dataclass(frozen=True)
class NotificationEmail:
    subject: str
    html: str
    text: str


def _app_url(path: str = "") -> str:
    base = settings.APP_BASE_URL.rstrip("/")
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def _render_email(
    *,
    preheader: str,
    title: str,
    body_html: str,
    cta_label: str,
    cta_url: str,
    footer_note: str,
) -> str:
    escaped_preheader = escape(preheader)
    escaped_title = escape(title)
    escaped_cta_label = escape(cta_label)
    escaped_cta_url = escape(cta_url, quote=True)
    escaped_footer_note = escape(footer_note)
    settings_url = escape(_app_url("?settings=notifications"), quote=True)

    return f"""
    <html>
    <body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#18181b;">
        <div style="display:none;max-height:0;overflow:hidden;color:#f4f4f5;">{escaped_preheader}</div>
        <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background:#f4f4f5;padding:40px 20px;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e4e4e7;">
                        <tr>
                            <td style="padding:32px 32px 0;">
                                <p style="margin:0;font-size:18px;font-weight:700;letter-spacing:0;color:#18181b;">InterAI</p>
                                <p style="margin:6px 0 0;font-size:12px;line-height:1.5;color:#71717a;">AI Interview Practice</p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:28px 32px 8px;">
                                <h1 style="margin:0 0 14px;font-size:24px;line-height:1.25;font-weight:700;color:#18181b;">{escaped_title}</h1>
                                <div style="font-size:15px;line-height:1.65;color:#3f3f46;">{body_html}</div>
                                <table cellpadding="0" cellspacing="0" role="presentation" style="margin:28px 0 22px;">
                                    <tr>
                                        <td style="background:#18181b;border-radius:7px;padding:13px 24px;">
                                            <a href="{escaped_cta_url}" style="display:inline-block;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;">{escaped_cta_label}</a>
                                        </td>
                                    </tr>
                                </table>
                                <p style="margin:0 0 6px;font-size:12px;line-height:1.5;color:#71717a;">{escaped_footer_note}</p>
                                <p style="margin:0;font-size:12px;line-height:1.5;color:#a1a1aa;">You can manage these emails from <a href="{settings_url}" style="color:#4f46e5;text-decoration:none;">notification settings</a>.</p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:20px 32px;border-top:1px solid #f4f4f5;">
                                <p style="margin:0;font-size:12px;line-height:1.5;color:#a1a1aa;">InterAI &mdash; Built for calmer, sharper interview practice.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def _plain_text(*lines: str) -> str:
    return "\n\n".join(line.strip() for line in lines if line and line.strip())


def build_inactivity_email(name: Optional[str], inactive_days: int) -> NotificationEmail:
    first_name = escape((name or "there").strip().split()[0] or "there")
    cta_url = _app_url()
    body = (
        f"<p style=\"margin:0 0 14px;\">Hi {first_name},</p>"
        f"<p style=\"margin:0 0 14px;\">It has been {inactive_days} days since your last practice session. A short round today can help keep your answers fresh and your confidence steady.</p>"
        "<p style=\"margin:0;\">Pick up where you left off with a focused interview practice session.</p>"
    )
    return NotificationEmail(
        subject="Time for another practice round?",
        html=_render_email(
            preheader="A quick practice session can help keep your interview skills fresh.",
            title="Ready for another practice round?",
            body_html=body,
            cta_label="Start practicing",
            cta_url=cta_url,
            footer_note="This reminder is based on your inactivity notification preference.",
        ),
        text=_plain_text(
            f"Hi {(name or 'there').strip().split()[0] or 'there'},",
            f"It has been {inactive_days} days since your last practice session.",
            f"Start practicing: {cta_url}",
            f"Manage notification settings: {_app_url('?settings=notifications')}",
        ),
    )


def build_target_date_email(name: Optional[str], target_date: str, days_left: int) -> NotificationEmail:
    first_name = escape((name or "there").strip().split()[0] or "there")
    cta_url = _app_url()
    timing = "today" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
    body = (
        f"<p style=\"margin:0 0 14px;\">Hi {first_name},</p>"
        f"<p style=\"margin:0 0 14px;\">Your target interview date is {escape(target_date)}. That means your interview is {escape(timing)}.</p>"
        "<p style=\"margin:0;\">Use today to rehearse your strongest stories, tighten your structure, and get one more realistic practice run in.</p>"
    )
    return NotificationEmail(
        subject="Your interview is coming up",
        html=_render_email(
            preheader="Your target interview date is getting close.",
            title="Your interview is coming up",
            body_html=body,
            cta_label="Practice now",
            cta_url=cta_url,
            footer_note="This reminder is based on your interview target date.",
        ),
        text=_plain_text(
            f"Hi {(name or 'there').strip().split()[0] or 'there'},",
            f"Your target interview date is {target_date}. Your interview is {timing}.",
            f"Practice now: {cta_url}",
            f"Manage notification settings: {_app_url('?settings=notifications')}",
        ),
    )


def build_weekly_summary_email(name: Optional[str], completed_count: int, average_score: float) -> NotificationEmail:
    first_name = escape((name or "there").strip().split()[0] or "there")
    cta_url = _app_url()
    score_text = f"{average_score:.1f}/100" if completed_count else "not available yet"
    body = (
        f"<p style=\"margin:0 0 14px;\">Hi {first_name},</p>"
        f"<p style=\"margin:0 0 14px;\">Here is your InterAI progress for the last 7 days: <strong>{completed_count}</strong> completed interview{'s' if completed_count != 1 else ''} with an average score of <strong>{escape(score_text)}</strong>.</p>"
        "<p style=\"margin:0;\">Review your recent performance and choose the next area to sharpen.</p>"
    )
    return NotificationEmail(
        subject="Your weekly InterAI progress summary",
        html=_render_email(
            preheader="Your weekly interview practice progress is ready.",
            title="Your weekly progress summary",
            body_html=body,
            cta_label="Review progress",
            cta_url=cta_url,
            footer_note="This summary is sent because weekly performance emails are enabled.",
        ),
        text=_plain_text(
            f"Hi {(name or 'there').strip().split()[0] or 'there'},",
            f"Last 7 days: {completed_count} completed interviews. Average score: {score_text}.",
            f"Review progress: {cta_url}",
            f"Manage notification settings: {_app_url('?settings=notifications')}",
        ),
    )


def build_streak_email(name: Optional[str]) -> NotificationEmail:
    first_name = escape((name or "there").strip().split()[0] or "there")
    cta_url = _app_url()
    body = (
        f"<p style=\"margin:0 0 14px;\">Hi {first_name},</p>"
        "<p style=\"margin:0 0 14px;\">You practiced yesterday. One focused session today keeps that momentum alive.</p>"
        "<p style=\"margin:0;\">A quick round is enough to stay warm and build consistency.</p>"
    )
    return NotificationEmail(
        subject="Keep your practice streak going",
        html=_render_email(
            preheader="Practice today to keep your interview momentum going.",
            title="Keep your practice streak going",
            body_html=body,
            cta_label="Continue streak",
            cta_url=cta_url,
            footer_note="This reminder is based on your streak notification preference.",
        ),
        text=_plain_text(
            f"Hi {(name or 'there').strip().split()[0] or 'there'},",
            "You practiced yesterday. Practice today to keep your momentum going.",
            f"Continue streak: {cta_url}",
            f"Manage notification settings: {_app_url('?settings=notifications')}",
        ),
    )


def send_notification_email(to_email: str, email: NotificationEmail) -> bool:
    smtp_email = settings.SMTP_EMAIL
    smtp_password = settings.SMTP_PASSWORD

    if not smtp_email or not smtp_password:
        logger.warning("SMTP not configured - notification email could not be sent for %s", stable_hash(to_email, "email"))
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg["Subject"] = email.subject
    msg.attach(MIMEText(email.text, "plain"))
    msg.attach(MIMEText(email.html, "html"))

    try:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        logger.error("Failed to send notification email for %s", stable_hash(to_email, "email"))
        return False
