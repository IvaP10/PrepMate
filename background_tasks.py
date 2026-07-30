# ============================================================================
# MODULE: background_tasks.py
# PURPOSE: Hourly subscription-expiry sweeper (runs in app lifespan).
# STRUCTURE:
#   - check_expired_subscriptions() infinite loop (lines 17-28)
#   - _expire_subscriptions() worker (lines 31-70)
# ENDPOINTS: none
# DEPENDS ON: database
# CONSUMED BY: app.py (started/cancelled in lifespan)
# DATA TABLES: Subscriptions (read+write), UserInfo (write plan_type/is_unlimited)
# ============================================================================

import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta

from database import get_db_connection, return_db_connection
from notification_email import (
    build_inactivity_email,
    build_streak_email,
    build_target_date_email,
    build_weekly_summary_email,
    send_notification_email,
)

logger = logging.getLogger("background_tasks")

SUBSCRIPTION_CHECK_INTERVAL_SECONDS = 3600

async def check_expired_subscriptions():
    while True:
        try:
            await asyncio.sleep(SUBSCRIPTION_CHECK_INTERVAL_SECONDS)
            await _expire_subscriptions()
        except asyncio.CancelledError:
            logger.info("Subscription checker task cancelled")
            break
        except Exception:
            logger.error("Error in subscription expiry background task")
            await asyncio.sleep(60)

async def _expire_subscriptions():
    def _run() -> int:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT subscription_id, user_id, is_unlimited
                FROM Subscriptions
                WHERE status = 'active' AND end_date < %s
                """,
                (datetime.now(timezone.utc),)
            )
            expired = cursor.fetchall()

            if not expired:
                return 0

            for sub_id, user_id, is_unlimited in expired:
                cursor.execute(
                    "UPDATE Subscriptions SET status = 'expired' WHERE subscription_id = %s",
                    (sub_id,)
                )
                if is_unlimited:
                    cursor.execute(
                        "UPDATE UserInfo SET plan_type = 'starter', is_unlimited = FALSE WHERE user_id = %s",
                        (user_id,)
                    )

            conn.commit()
            return len(expired)
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            return_db_connection(conn)

    count = await asyncio.to_thread(_run)
    if count:
        logger.info("Expired %d subscription(s) via background task", count)


NOTIFICATION_CHECK_INTERVAL_SECONDS = 3600 # Run every hour
NOTIFICATION_SENT_KEY = "_sent"

async def process_notification_reminders():
    # Run once immediately on start
    try:
        await _run_notification_checks()
    except Exception as e:
        logger.error("Error in initial notification checker run: %s", str(e))
        
    while True:
        try:
            await asyncio.sleep(NOTIFICATION_CHECK_INTERVAL_SECONDS)
            await _run_notification_checks()
        except asyncio.CancelledError:
            logger.info("Notification checker task cancelled")
            break
        except Exception as e:
            logger.error("Error in notification checker background task: %s", str(e))

async def _run_notification_checks():
    today_date = datetime.now().date()
    today_token = today_date.isoformat()
    week_key = today_date.isocalendar()
    current_week = f"{week_key.year}-W{week_key.week:02d}"

    def _sent_token(prefs: dict, notification_type: str):
        sent = prefs.get(NOTIFICATION_SENT_KEY)
        if not isinstance(sent, dict):
            return None
        return sent.get(notification_type)

    def _mark_sent(prefs: dict, notification_type: str, token: str):
        sent = prefs.get(NOTIFICATION_SENT_KEY)
        if not isinstance(sent, dict):
            sent = {}
            prefs[NOTIFICATION_SENT_KEY] = sent
        sent[notification_type] = token

    def _run():
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Query all users with login info and preferences
            cursor.execute(
                """
                SELECT u.user_id, u.full_name, l.email, u.notification_prefs
                FROM UserInfo u
                JOIN Login l ON u.user_id = l.user_id
                """
            )
            users = cursor.fetchall()
            
            for user_id, name, email, prefs_raw in users:
                if not prefs_raw:
                    continue
                try:
                    prefs = json.loads(prefs_raw) if isinstance(prefs_raw, str) else prefs_raw
                except Exception:
                    continue
                if not isinstance(prefs, dict):
                    continue
                prefs_changed = False
                
                # Check Inactivity Reminder
                inactive_days = prefs.get("inactive_reminder_days")
                if inactive_days is not None:
                    # Find last activity (interview creation date)
                    cursor.execute(
                        "SELECT MAX(created_at) FROM Interviews WHERE user_id = %s",
                        (user_id,)
                    )
                    last_act_row = cursor.fetchone()
                    last_activity = last_act_row[0] if last_act_row and last_act_row[0] else None
                    
                    if not last_activity:
                        # Fallback to user creation date
                        cursor.execute(
                            "SELECT date_created FROM UserInfo WHERE user_id = %s",
                            (user_id,)
                        )
                        creation_row = cursor.fetchone()
                        last_activity = creation_row[0] if creation_row else None
                    
                    if last_activity:
                        # Calculate diff
                        now = datetime.now(last_activity.tzinfo) if last_activity.tzinfo else datetime.now()
                        delta = now - last_activity
                        if delta.days >= inactive_days and _sent_token(prefs, "inactivity") != today_token:
                            sent = send_notification_email(
                                email,
                                build_inactivity_email(name, delta.days),
                            )
                            if sent:
                                _mark_sent(prefs, "inactivity", today_token)
                                prefs_changed = True
                
                # Check Interview Target Date
                target_date_str = prefs.get("target_date")
                if target_date_str:
                    try:
                        target_date_str = target_date_str.strip()
                        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
                        days_left = (target_date - today_date).days
                        target_token = f"{target_date_str}:{today_token}"
                        if 0 <= days_left <= 7 and _sent_token(prefs, "target_date") != target_token:
                            sent = send_notification_email(
                                email,
                                build_target_date_email(name, target_date_str, days_left),
                            )
                            if sent:
                                _mark_sent(prefs, "target_date", target_token)
                                prefs_changed = True
                    except Exception:
                        pass
                
                # Check Weekly Performance Summary
                if prefs.get("weekly_summary") and _sent_token(prefs, "weekly_summary") != current_week:
                    # Retrieve interview scores from last 7 days
                    cursor.execute(
                        """
                        SELECT AVG(overall_score), COUNT(*) 
                        FROM Interviews 
                        WHERE user_id = %s AND completed_at >= NOW() - INTERVAL '7 days' AND overall_score IS NOT NULL
                        """,
                        (user_id,)
                    )
                    perf_row = cursor.fetchone()
                    avg_score = perf_row[0] if perf_row and perf_row[0] is not None else 0.0
                    count = perf_row[1] if perf_row else 0
                    sent = send_notification_email(
                        email,
                        build_weekly_summary_email(name, count, float(avg_score)),
                    )
                    if sent:
                        _mark_sent(prefs, "weekly_summary", current_week)
                        prefs_changed = True
                
                # Check Streak Reminder
                if prefs.get("streak_reminder"):
                    # Calculate streak or check if they practiced today
                    cursor.execute(
                        "SELECT MAX(created_at) FROM Interviews WHERE user_id = %s",
                        (user_id,)
                    )
                    last_act_row = cursor.fetchone()
                    last_act = last_act_row[0] if last_act_row and last_act_row[0] else None
                    if last_act:
                        now = datetime.now(last_act.tzinfo) if last_act.tzinfo else datetime.now()
                        delta = now - last_act
                        if delta.days == 1 and _sent_token(prefs, "streak_reminder") != today_token:
                            sent = send_notification_email(
                                email,
                                build_streak_email(name),
                            )
                            if sent:
                                _mark_sent(prefs, "streak_reminder", today_token)
                                prefs_changed = True

                if prefs_changed:
                    cursor.execute(
                        "UPDATE UserInfo SET notification_prefs = %s WHERE user_id = %s",
                        (json.dumps(prefs), user_id)
                    )
                    conn.commit()

            conn.commit()
            
        except Exception as e:
            conn.rollback()
            logger.error("Failed to run notification checks in database: %s", str(e))
        finally:
            cursor.close()
            return_db_connection(conn)

    await asyncio.to_thread(_run)


async def cleanup_stale_interviews():
    # Run once immediately on start
    try:
        await _expire_stale_interviews()
        await _recover_orphaned_analysis_attempts()
    except Exception as e:
        logger.error("Error in initial stale interview cleanup run: %s", str(e))

    while True:
        try:
            await asyncio.sleep(60)  # check every minute
            await _expire_stale_interviews()
            await _recover_orphaned_analysis_attempts()
        except asyncio.CancelledError:
            logger.info("Stale interview cleaner task cancelled")
            break
        except Exception as e:
            logger.error("Error in stale interview cleaner background task: %s", str(e))
            await asyncio.sleep(60)


async def _recover_orphaned_analysis_attempts() -> None:
    """Repair completed attempts that finalized but failed before job creation."""
    from analysis_pipeline import (
        ANALYSIS_STAGE_VERSION,
        SESSION_PERFORMANCE_VERSION,
        enqueue_analysis_result,
    )
    from database import async_execute

    rows = await async_execute(
        """
        SELECT i.interview_id, i.user_id
        FROM Interviews i
        WHERE i.attempt_status = 'completed'
          AND i.status IN (
              'analysis_pending', 'analysis_running',
              'completed', 'partial', 'failed'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM SessionPerformanceAnalyses analysis
              WHERE analysis.interview_id = i.interview_id
                AND analysis.user_id = i.user_id
                AND analysis.schema_version = %s
                AND analysis.is_current = TRUE
                AND analysis.status = 'ready'
                AND analysis.analysis_json_encrypted IS NOT NULL
                AND analysis.evidence_index_encrypted IS NOT NULL
          )
          AND NOT EXISTS (
              SELECT 1
              FROM AnalysisJobs job
              WHERE job.interview_id = i.interview_id
                AND job.user_id = i.user_id
                AND job.producer_version = %s
          )
        ORDER BY COALESCE(i.completed_at, i.created_at)
        LIMIT 20
        """,
        (SESSION_PERFORMANCE_VERSION, ANALYSIS_STAGE_VERSION),
        fetchall=True,
    )
    for interview_id, user_id in rows or []:
        try:
            result = await enqueue_analysis_result(
                str(interview_id),
                str(user_id),
                "orphaned_analysis_recovery",
                force_canonical_rebuild=True,
            )
            state_name = str(result.get("state") or "rejected")
            job_id = result.get("job_id")
            await async_execute(
                """
                UPDATE Interviews
                SET analysis_job_id = COALESCE(%s, analysis_job_id),
                    analysis_status = CASE
                        WHEN %s IN ('queued', 'already_running') THEN 'queued'
                        WHEN %s IN ('ready', 'report_ready') THEN 'completed'
                        ELSE 'failed'
                    END,
                    feedback_summary = CASE
                        WHEN %s IN ('queued', 'already_running')
                        THEN 'Interview complete. Async analysis is queued.'
                        WHEN %s IN ('ready', 'report_ready')
                        THEN feedback_summary
                        ELSE 'Interview complete, but analysis needs attention.'
                    END
                WHERE interview_id = %s AND user_id = %s
                  AND attempt_status = 'completed'
                """,
                (
                    job_id,
                    state_name,
                    state_name,
                    state_name,
                    state_name,
                    interview_id,
                    user_id,
                ),
            )
        except Exception:
            logger.exception(
                "Could not recover orphaned analysis attempt %s",
                interview_id,
            )


async def _expire_stale_interviews():
    def _get_stale():
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                WITH expired_interviews AS (
                    UPDATE Interviews
                    SET status = 'cancelled', completed_at = COALESCE(completed_at, NOW()),
                        attempt_status = 'incomplete', analysis_status = 'not_requested',
                        completion_kind = 'recovery_expired', recovery_deadline_at = NULL,
                        lifecycle_revision = lifecycle_revision + 1,
                        overall_score = NULL,
                        duration_seconds = CASE
                            WHEN started_at IS NULL THEN duration_seconds
                            ELSE GREATEST(0, EXTRACT(EPOCH FROM (NOW() - started_at))::integer)
                        END,
                        feedback_summary = 'Attempt incomplete because connection recovery expired.',
                        settings = (COALESCE(settings, '{}'::jsonb) - 'recovery_deadline' - 'recovery_reason')
                            || jsonb_build_object('abandonment_reason', 'recovery_timeout')
                    WHERE status = 'recovering'
                      AND settings ? 'recovery_deadline'
                      AND (settings->>'recovery_deadline')::timestamptz <= NOW()
                    RETURNING interview_id, user_id, completed_at
                ),
                closed_rounds AS (
                    UPDATE TechnicalInterviewRounds round
                    SET status = 'cancelled',
                        completed_at = COALESCE(
                            round.completed_at,
                            expired.completed_at,
                            NOW()
                        )
                    FROM expired_interviews expired
                    WHERE round.interview_id = expired.interview_id
                      AND round.user_id = expired.user_id
                      AND round.status NOT IN (
                          'submitted', 'completed', 'expired', 'cancelled'
                      )
                    RETURNING round.round_id
                )
                SELECT interview_id, user_id FROM expired_interviews
                """
            )
            expired_recoveries = cursor.fetchall()
            recovered_expired = len(expired_recoveries)
            conn.commit()
            if recovered_expired:
                logger.info("Marked %d expired recovery attempt(s) incomplete", recovered_expired)
            cursor.execute(
                """
                SELECT interview_id, user_id
                FROM Interviews
                WHERE status = 'in_progress'
                  AND (
                      deadline_at <= NOW()
                      OR (
                          deadline_at IS NULL
                          AND COALESCE(started_at, created_at) < NOW() - INTERVAL '60 minutes'
                      )
                  )
                """
            )
            return expired_recoveries, cursor.fetchall()
        finally:
            cursor.close()
            return_db_connection(conn)

    expired_recoveries, stale_interviews = await asyncio.to_thread(_get_stale)
    if expired_recoveries:
        from interview import _record_server_integrity_event
        for expired_interview_id, expired_user_id in expired_recoveries:
            await _record_server_integrity_event(
                expired_interview_id,
                expired_user_id,
                "recovery_expired",
            )
    if not stale_interviews:
        return

    from analysis_pipeline import enqueue_analysis
    from database import async_execute

    for interview_id, user_id in stale_interviews:
        try:
            finalized = await async_execute(
                """
                WITH finalized_interview AS (
                    UPDATE Interviews
                    SET status = 'analysis_pending',
                        attempt_status = 'completed', analysis_status = 'queued',
                        completion_kind = 'deadline', lifecycle_revision = lifecycle_revision + 1,
                        completed_at = NOW(),
                        feedback_summary = 'Interview complete. Auto-finalized due to 60-minute limit.'
                    WHERE interview_id = %s AND status = 'in_progress'
                    RETURNING interview_id, user_id, completed_at
                ),
                closed_rounds AS (
                    UPDATE TechnicalInterviewRounds round
                    SET status = 'expired',
                        completed_at = COALESCE(
                            round.completed_at,
                            finalized.completed_at,
                            NOW()
                        )
                    FROM finalized_interview finalized
                    WHERE round.interview_id = finalized.interview_id
                      AND round.user_id = finalized.user_id
                      AND round.status NOT IN (
                          'submitted', 'completed', 'expired', 'cancelled'
                      )
                    RETURNING round.round_id
                )
                SELECT interview_id FROM finalized_interview
                """,
                (interview_id,),
                fetchone=True,
            )
            if not finalized:
                continue
            job_id = await enqueue_analysis(interview_id, user_id, "auto_expire_60m")
            await async_execute(
                """
                UPDATE Interviews
                SET analysis_job_id = %s,
                    analysis_status = CASE WHEN %s IS NULL THEN 'failed' ELSE 'queued' END,
                    feedback_summary = CASE
                        WHEN %s IS NULL
                        THEN 'Interview complete, but analysis could not be queued.'
                        ELSE feedback_summary
                    END
                WHERE interview_id = %s AND attempt_status = 'completed'
                """,
                (job_id, job_id, job_id, interview_id),
            )
            logger.info("Auto-finalized stale interview %s due to 60m limit", interview_id)
        except Exception as e:
            logger.error("Failed to auto-finalize stale interview %s: %s", interview_id, str(e))
