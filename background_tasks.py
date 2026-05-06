import asyncio
import logging
from datetime import datetime

from database import get_db_connection, return_db_connection

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
                (datetime.utcnow(),)
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
                        "UPDATE UserInfo SET plan_type = 'free', is_unlimited = FALSE WHERE user_id = %s",
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
