from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from pydantic import BaseModel
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone
import logging
import uuid
import hmac
import hashlib
import razorpay

from auth import get_current_user
from database import get_db
from config import settings as app_settings
from pricing import PRICING
from security_utils import redact_text, stable_hash

router = APIRouter(tags=["Payment"])
logger = logging.getLogger("ai_interviewer.payment")

razorpay_client = None
if app_settings.RAZORPAY_KEY_ID and app_settings.RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET))

RAZORPAY_WEBHOOK_SECRET = app_settings.RAZORPAY_WEBHOOK_SECRET

MEMBERSHIP_PLANS = {
    "starter": {
        "amount": 799.0,
        "currency": "INR",
        "interviews": 5,
        "is_unlimited": False,
        "duration_days": 30,
        "name": "Starter",
    },
    "pro": {
        "amount": 1499.0,
        "currency": "INR",
        "interviews": None,
        "is_unlimited": True,
        "duration_days": 30,
        "name": "Pro",
    },
    "pro_annual": {
        "amount": 11988.0,
        "currency": "INR",
        "interviews": None,
        "is_unlimited": True,
        "duration_days": 365,
        "name": "Pro Annual",
    },
}

class CreateSubscriptionRequest(BaseModel):
    plan_type: str
    payment_method: str
    provider: Optional[str] = 'razorpay'
    sessions: Optional[int] = None

class PaymentResponse(BaseModel):
    transaction_id: str
    amount: float
    status: str
    message: str
    interviews_credited: Optional[int] = None
    session_url: Optional[str] = None
    provider: Optional[str] = None

class SubscriptionResponse(BaseModel):
    subscription_id: str
    plan_type: str
    status: str
    start_date: datetime
    end_date: datetime
    auto_renew: bool
    interviews_remaining: Optional[int]
    is_unlimited: bool


def _apply_completed_transaction(cursor, user_id: str, credits_to_grant: Optional[int], subscription_id: Optional[str]) -> str:
    if subscription_id:
        cursor.execute(
            """
            UPDATE Subscriptions
            SET status = 'active'
            WHERE subscription_id = %s
            RETURNING plan_type, is_unlimited
            """,
            (subscription_id,)
        )
        subscription_row = cursor.fetchone()
        if not subscription_row:
            raise HTTPException(status_code=404, detail="Subscription not found")
        plan_type = subscription_row[0]
        is_unlimited = bool(subscription_row[1])
        cursor.execute(
            """
            UPDATE UserInfo
            SET plan_type = %s,
                is_unlimited = %s,
                interviews_remaining = CASE WHEN %s THEN interviews_remaining ELSE %s END
            WHERE user_id = %s
            """,
            (
                plan_type,
                is_unlimited,
                is_unlimited,
                credits_to_grant or 0,
                user_id,
            )
        )
        return "membership"

    if credits_to_grant is not None and credits_to_grant > 0:
        cursor.execute(
            "UPDATE UserInfo SET interviews_remaining = COALESCE(interviews_remaining, 0) + %s WHERE user_id = %s",
            (credits_to_grant, user_id)
        )
    return "purchase"

@router.get("/pricing")
async def get_pricing(
    sessions: int = 5,
    provider: str = "razorpay",
    current_user: Dict = Depends(get_current_user),
):
    if sessions < 1 or sessions > 100:
        raise HTTPException(status_code=400, detail="Sessions must be between 1 and 100")
    if provider != "razorpay":
        raise HTTPException(status_code=400, detail="Provider must be 'razorpay'")
    return PRICING.calculate_total(sessions, provider)

@router.post("/create-subscription", response_model=PaymentResponse)
async def create_subscription(
    request: CreateSubscriptionRequest,
    current_user: Dict = Depends(get_current_user)
):
    is_credit_purchase = request.plan_type == "credits"
    membership_plan = MEMBERSHIP_PLANS.get(request.plan_type)

    if not is_credit_purchase and not membership_plan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported plan type"
        )

    if is_credit_purchase and (not request.sessions or request.sessions < 1 or request.sessions > 100):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sessions must be between 1 and 100"
        )

    if request.provider != "razorpay":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider must be 'razorpay'"
        )

    if is_credit_purchase:
        pricing = PRICING.calculate_total(request.sessions, request.provider)
        amount = pricing["total"]
        currency = pricing["currency"]
        product_name = f"InterAI {request.sessions} Interview Credits"
        cancel_url = f"{app_settings.APP_BASE_URL}/checkout?sessions={request.sessions}"
    else:
        amount = membership_plan["amount"]
        currency = membership_plan["currency"]
        product_name = f"InterAI {membership_plan['name']} Membership"
        cancel_url = f"{app_settings.APP_BASE_URL}/checkout?plan={request.plan_type}"

    with get_db() as connection:
        cursor = connection.cursor()

        try:
            connection.autocommit = False

            cursor.execute(
                """
                SELECT subscription_id, status, end_date
                FROM Subscriptions
                WHERE user_id = %s AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (current_user["user_id"],)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE Subscriptions SET status = 'cancelled', auto_renew = FALSE WHERE subscription_id = %s",
                    (existing[0],)
                )
                logger.info("Cancelled previous subscription %s for %s", stable_hash(existing[0], "sub"), stable_hash(current_user["user_id"], "user"))

            transaction_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=PRICING.TRANSACTION_EXPIRY_MINUTES)
            session_url = None
            razorpay_order_id = None
            subscription_id = None

            if membership_plan:
                subscription_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO Subscriptions (
                        subscription_id, user_id, plan_type, status,
                        start_date, end_date, auto_renew, is_unlimited, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        subscription_id,
                        current_user["user_id"],
                        request.plan_type,
                        "pending",
                        now,
                        now + timedelta(days=membership_plan["duration_days"]),
                        True,
                        membership_plan["is_unlimited"],
                        now,
                    )
                )

            if request.provider == "razorpay" and razorpay_client:
                try:
                    order = razorpay_client.order.create({
                        "amount": int(amount * 100),
                        "currency": currency,
                        "receipt": transaction_id,
                        "payment_capture": "1",
                    })
                    razorpay_order_id = order["id"]
                    session_url = razorpay_order_id
                except Exception as e:
                    logger.error("Razorpay order creation failed: %s", redact_text(e))
                    raise HTTPException(status_code=500, detail="Failed to initialize Razorpay order")
            else:
                raise HTTPException(status_code=400, detail="Razorpay is not configured")

            effective_txn_id = razorpay_order_id if razorpay_order_id else transaction_id

            cursor.execute(
                """
                INSERT INTO Transactions (
                    transaction_id, user_id, subscription_id, amount,
                    credits_purchased, currency, payment_method, payment_provider,
                    status, expires_at, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    effective_txn_id, current_user["user_id"],
                    subscription_id,
                    amount, membership_plan["interviews"] if membership_plan else request.sessions, currency,
                    request.payment_method, request.provider,
                    "pending", expires_at, now,
                )
            )

            connection.commit()
            connection.autocommit = True
            logger.info(
                "Pending transaction created: txn=%s, user=%s, plan=%s, amount=%.2f %s",
                stable_hash(effective_txn_id, "txn"), stable_hash(current_user["user_id"], "user"), request.plan_type, amount, currency,
            )

            return {
                "transaction_id": effective_txn_id,
                "amount": amount,
                "status": "pending",
                "message": f"Proceed to {request.provider} to complete checkout.",
                "session_url": session_url,
                "provider": request.provider,
            }

        except Exception as e:
            connection.rollback()
            connection.autocommit = True
            logger.error("Failed to create subscription")
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail="Failed to create subscription")

        finally:
            cursor.close()

class VerifyRazorpayRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

@router.post("/verify-razorpay")
async def verify_razorpay_payment(
    request: VerifyRazorpayRequest,
    current_user: Dict = Depends(get_current_user)
):
    key_secret = app_settings.RAZORPAY_KEY_SECRET
    if not key_secret:
        raise HTTPException(status_code=500, detail="Payment verification not configured")

    message = f"{request.razorpay_order_id}|{request.razorpay_payment_id}"
    expected_signature = hmac.HMAC(
        key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, request.razorpay_signature):
        logger.warning(
            "Razorpay signature mismatch for order %s, user %s",
            stable_hash(request.razorpay_order_id, "order"), stable_hash(current_user["user_id"], "user")
        )
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    with get_db() as connection:
        cursor = connection.cursor()
        try:
            connection.autocommit = False

            cursor.execute(
                "SELECT status, credits_purchased, user_id, subscription_id FROM Transactions WHERE transaction_id = %s FOR UPDATE",
                (request.razorpay_order_id,)
            )
            txn = cursor.fetchone()

            if not txn:
                connection.rollback()
                raise HTTPException(status_code=404, detail="Transaction not found")

            if txn[0] == "completed":
                if txn[3]:
                    cursor.execute("SELECT status FROM Subscriptions WHERE subscription_id = %s", (txn[3],))
                    sub_status = cursor.fetchone()
                    if sub_status and sub_status[0] == "pending":
                        _apply_completed_transaction(cursor, current_user["user_id"], txn[1], txn[3])
                        connection.commit()
                    else:
                        connection.rollback()
                else:
                    connection.rollback()
                return {"success": True, "message": "Payment already verified"}

            if txn[0] != "pending":
                connection.rollback()
                raise HTTPException(status_code=400, detail=f"Transaction in unexpected state: {txn[0]}")

            if txn[2] != current_user["user_id"]:
                connection.rollback()
                raise HTTPException(status_code=403, detail="Transaction does not belong to this user")

            credits_to_grant = txn[1]
            subscription_id = txn[3]

            cursor.execute(
                "UPDATE Transactions SET status = 'completed' WHERE transaction_id = %s",
                (request.razorpay_order_id,)
            )

            result_kind = _apply_completed_transaction(cursor, current_user["user_id"], credits_to_grant, subscription_id)

            connection.commit()
            logger.info(
                "Payment verified: user=%s, subscription=%s, order=%s",
                stable_hash(current_user["user_id"], "user"),
                stable_hash(subscription_id, "sub") if subscription_id else "sub:none",
                stable_hash(request.razorpay_order_id, "order"),
            )

            return {
                "success": True,
                "message": "Membership activated successfully!" if subscription_id else "Purchase completed successfully!",
                "interviews": credits_to_grant,
                "kind": result_kind,
            }

        except HTTPException:
            raise
        except Exception:
            connection.rollback()
            logger.error("Payment verification error")
            raise HTTPException(status_code=500, detail="Payment verification failed")
        finally:
            connection.autocommit = True
            cursor.close()

@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(current_user: Dict = Depends(get_current_user)):
    with get_db() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT s.subscription_id, s.plan_type, s.status,
                       s.start_date, s.end_date, s.auto_renew,
                       s.is_unlimited, u.interviews_remaining
                FROM Subscriptions s
                JOIN UserInfo u ON s.user_id = u.user_id
                WHERE s.user_id = %s
                ORDER BY s.created_at DESC
                LIMIT 1
                """,
                (current_user["user_id"],)
            )

            row = cursor.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No subscription found"
                )

            return SubscriptionResponse(**{
                "subscription_id": row[0],
                "plan_type": row[1],
                "status": row[2],
                "start_date": row[3],
                "end_date": row[4],
                "auto_renew": row[5],
                "is_unlimited": row[6] or False,
                "interviews_remaining": row[7] if not row[6] else None
            })

        finally:
            cursor.close()

@router.post("/cancel-subscription")
async def cancel_subscription(current_user: Dict = Depends(get_current_user)):
    with get_db() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT subscription_id, status, is_unlimited
                FROM Subscriptions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (current_user["user_id"],)
            )

            row = cursor.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No subscription found"
                )

            subscription_id = row[0]
            current_status = row[1]
            is_unlimited = row[2]

            if current_status == "cancelled":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Subscription already cancelled"
                )

            cursor.execute(
                """
                UPDATE Subscriptions
                SET status = 'cancelled', auto_renew = FALSE
                WHERE subscription_id = %s
                """,
                (subscription_id,)
            )

            if is_unlimited:
                cursor.execute(
                    """
                    UPDATE UserInfo
                    SET is_unlimited = FALSE,
                        plan_type = 'free',
                        interviews_remaining = COALESCE(interviews_remaining, 0)
                    WHERE user_id = %s
                    """,
                    (current_user["user_id"],)
                )

            connection.commit()
            logger.info("Subscription cancelled: %s", stable_hash(current_user["user_id"], "user"))

            return {
                "success": True,
                "message": "Subscription cancelled. Remaining interviews are still available."
            }

        except HTTPException:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            logger.error("Failed to cancel subscription")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel subscription"
            )

        finally:
            cursor.close()

@router.get("/transactions")
async def get_transactions(
    current_user: Dict = Depends(get_current_user),
    limit: int = Query(10, ge=1, le=100)
):
    with get_db() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT transaction_id, amount, currency, payment_method, payment_provider, status, credits_purchased, created_at
                FROM Transactions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (current_user["user_id"], limit)
            )

            rows = cursor.fetchall()
            transactions = []

            for row in rows:
                transactions.append({
                    "transaction_id": row[0],
                    "amount": float(row[1]),
                    "currency": row[2],
                    "payment_method": row[3],
                    "payment_provider": row[4],
                    "status": row[5],
                    "credits_purchased": row[6],
                    "created_at": row[7].isoformat() if row[7] else None
                })

            return {
                "transactions": transactions,
                "total_count": len(transactions)
            }

        finally:
            cursor.close()

@router.post("/toggle-auto-renew")
async def toggle_auto_renew(current_user: Dict = Depends(get_current_user)):
    with get_db() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT subscription_id, auto_renew
                FROM Subscriptions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (current_user["user_id"],)
            )

            row = cursor.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No subscription found"
                )

            subscription_id = row[0]
            new_auto_renew = not row[1]

            cursor.execute(
                "UPDATE Subscriptions SET auto_renew = %s WHERE subscription_id = %s",
                (new_auto_renew, subscription_id)
            )

            connection.commit()
            logger.info("Auto-renew toggled: user=%s, value=%s", stable_hash(current_user["user_id"], "user"), new_auto_renew)

            return {
                "success": True,
                "auto_renew": new_auto_renew,
                "message": f"Auto-renew {'enabled' if new_auto_renew else 'disabled'}"
            }

        except HTTPException:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            logger.error("Failed to toggle auto-renew")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to toggle auto-renew"
            )

        finally:
            cursor.close()

@router.post("/razorpay/webhook")
async def razorpay_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("x-razorpay-signature")

    if not sig_header or not RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=400, detail="Missing signature or secret")

    try:
        expected_sig = hmac.HMAC(
            key=RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, sig_header):
            raise HTTPException(status_code=400, detail="Invalid signature")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Signature verification failed")

    data = await request.json()
    if data.get('event') in ('order.paid', 'payment.captured'):
        payment_entity = data['payload']['payment']['entity']
        order_id = payment_entity.get('order_id')

        if order_id:
            with get_db() as conn:
                cursor = conn.cursor()
                try:
                    conn.autocommit = False
                    cursor.execute(
                        "SELECT status, credits_purchased, user_id, subscription_id FROM Transactions WHERE transaction_id = %s FOR UPDATE",
                        (order_id,)
                    )
                    txn = cursor.fetchone()
                    if txn and txn[0] == 'pending':
                        credits_to_grant = txn[1]
                        user_id = txn[2]
                        subscription_id = txn[3]

                        cursor.execute(
                            "UPDATE Transactions SET status = 'completed' WHERE transaction_id = %s",
                            (order_id,)
                        )

                        result_kind = _apply_completed_transaction(cursor, user_id, credits_to_grant, subscription_id)

                        conn.commit()
                        logger.info(
                            "Razorpay webhook completed: user=%s, kind=%s, order=%s",
                            stable_hash(user_id, "user"),
                            result_kind,
                            stable_hash(order_id, "order"),
                        )
                    else:
                        conn.rollback()
                except Exception:
                    conn.rollback()
                    logger.error("Razorpay webhook DB error for order=%s", stable_hash(order_id, "order"))
                    raise HTTPException(status_code=500, detail="Webhook processing failed")
                finally:
                    conn.autocommit = True
                    cursor.close()

    return {"status": "success"}
