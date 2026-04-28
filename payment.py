from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone
import logging
import uuid
import hmac
import hashlib
import stripe
import razorpay

from auth import get_current_user
from database import get_db
from config import settings as app_settings
from pricing import PRICING

router = APIRouter(tags=["Payment"])
logger = logging.getLogger("ai_interviewer.payment")

stripe.api_key = app_settings.STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET = app_settings.STRIPE_WEBHOOK_SECRET

razorpay_client = None
if app_settings.RAZORPAY_KEY_ID and app_settings.RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET))

RAZORPAY_WEBHOOK_SECRET = app_settings.RAZORPAY_WEBHOOK_SECRET

class CreateSubscriptionRequest(BaseModel):
    plan_type: str
    payment_method: str
    provider: Optional[str] = 'stripe'
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

@router.get("/pricing")
async def get_pricing(
    sessions: int = 5,
    provider: str = "razorpay",
    current_user: Dict = Depends(get_current_user),
):
    if sessions < 1 or sessions > 100:
        raise HTTPException(status_code=400, detail="Sessions must be between 1 and 100")
    if provider not in ("razorpay", "stripe"):
        raise HTTPException(status_code=400, detail="Provider must be 'razorpay' or 'stripe'")
    return PRICING.calculate_total(sessions, provider)

@router.post("/create-subscription", response_model=PaymentResponse)
async def create_subscription(
    request: CreateSubscriptionRequest,
    current_user: Dict = Depends(get_current_user)
):
    if request.plan_type != "credits":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only 'credits' plan type is currently supported"
        )

    if not request.sessions or request.sessions < 1 or request.sessions > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sessions must be between 1 and 100"
        )

    if request.provider not in ("razorpay", "stripe"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider must be 'razorpay' or 'stripe'"
        )

    pricing = PRICING.calculate_total(request.sessions, request.provider)
    amount = pricing["total"]
    currency = pricing["currency"]

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
                logger.info("Cancelled previous subscription %s for user %s", existing[0], current_user["user_id"])

            transaction_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=PRICING.TRANSACTION_EXPIRY_MINUTES)
            session_url = None
            razorpay_order_id = None

            if request.provider == "stripe" and stripe.api_key:
                try:
                    checkout_session = stripe.checkout.Session.create(
                        payment_method_types=["card"],
                        line_items=[{
                            "price_data": {
                                "currency": currency.lower(),
                                "product_data": {
                                    "name": f"InterAI {request.sessions} Interview Credits",
                                },
                                "unit_amount": int(amount * 100),
                            },
                            "quantity": 1,
                        }],
                        mode="payment",
                        success_url=f"{app_settings.APP_BASE_URL}/dashboard?session_id={{CHECKOUT_SESSION_ID}}",
                        cancel_url=f"{app_settings.APP_BASE_URL}/checkout?sessions={request.sessions}",
                        client_reference_id=transaction_id,
                        expires_at=int(expires_at.timestamp()),
                    )
                    session_url = checkout_session.url
                except Exception as e:
                    logger.error("Stripe session creation failed: %s", e)
                    raise HTTPException(status_code=500, detail="Failed to initialize Stripe session")

            elif request.provider == "razorpay" and razorpay_client:
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
                    logger.error("Razorpay order creation failed: %s", e)
                    raise HTTPException(status_code=500, detail="Failed to initialize Razorpay order")
            else:
                raise HTTPException(status_code=400, detail="Payment provider not configured")

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
                    None,  # No subscription_id — avoids FK violation for credit purchases
                    amount, request.sessions, currency,
                    request.payment_method, request.provider,
                    "pending", expires_at, now,
                )
            )

            connection.commit()
            connection.autocommit = True
            logger.info(
                "Pending transaction created: txn=%s, user=%s, sessions=%d, amount=%.2f %s",
                effective_txn_id, current_user["user_id"], request.sessions, amount, currency,
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
            logger.exception("Failed to create subscription")
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
    """
    Verify Razorpay payment signature and credit the user.
    Uses SELECT ... FOR UPDATE to prevent double-crediting from concurrent
    calls with the webhook endpoint.
    """
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
            request.razorpay_order_id, current_user["user_id"]
        )
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    with get_db() as connection:
        cursor = connection.cursor()
        try:
            connection.autocommit = False

            cursor.execute(
                "SELECT status, credits_purchased, user_id FROM Transactions WHERE transaction_id = %s FOR UPDATE",
                (request.razorpay_order_id,)
            )
            txn = cursor.fetchone()

            if not txn:
                connection.rollback()
                raise HTTPException(status_code=404, detail="Transaction not found")

            if txn[0] == "completed":
                connection.rollback()
                return {"success": True, "message": "Payment already verified", "credits": txn[1]}

            if txn[0] != "pending":
                connection.rollback()
                raise HTTPException(status_code=400, detail=f"Transaction in unexpected state: {txn[0]}")

            if txn[2] != current_user["user_id"]:
                connection.rollback()
                raise HTTPException(status_code=403, detail="Transaction does not belong to this user")

            credits_to_grant = txn[1]

            cursor.execute(
                "UPDATE Transactions SET status = 'completed' WHERE transaction_id = %s",
                (request.razorpay_order_id,)
            )

            if credits_to_grant is not None and credits_to_grant > 0:
                cursor.execute(
                    "UPDATE UserInfo SET interviews_remaining = COALESCE(interviews_remaining, 0) + %s WHERE user_id = %s",
                    (credits_to_grant, current_user["user_id"])
                )

            connection.commit()
            logger.info(
                "Payment verified & credited: user=%s, credits=%s, order=%s",
                current_user["user_id"], credits_to_grant, request.razorpay_order_id
            )

            return {
                "success": True,
                "message": f"{credits_to_grant} credits added successfully!",
                "credits": credits_to_grant,
            }

        except HTTPException:
            raise
        except Exception:
            connection.rollback()
            logger.exception("Payment verification error")
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
            logger.info(f"Subscription cancelled: user={current_user['user_id']}")

            return {
                "success": True,
                "message": "Subscription cancelled. Remaining interviews are still available."
            }

        except HTTPException:
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            logger.exception("Failed to cancel subscription")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel subscription"
            )

        finally:
            cursor.close()

@router.get("/transactions")
async def get_transactions(
    current_user: Dict = Depends(get_current_user),
    limit: int = 10
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
            logger.info(f"Auto-renew toggled: user={current_user['user_id']}, value={new_auto_renew}")

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
            logger.exception("Failed to toggle auto-renew")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to toggle auto-renew"
            )

        finally:
            cursor.close()

@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=400, detail="Missing signature or secret")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        transaction_id = session.get('client_reference_id')

        if transaction_id:
            with get_db() as conn:
                cursor = conn.cursor()
                try:
                    conn.autocommit = False
                    cursor.execute(
                        "SELECT status, credits_purchased, user_id FROM Transactions WHERE transaction_id = %s FOR UPDATE",
                        (transaction_id,)
                    )
                    txn = cursor.fetchone()
                    if txn and txn[0] == 'pending':
                        credits_to_grant = txn[1]
                        user_id = txn[2]

                        cursor.execute(
                            "UPDATE Transactions SET status = 'completed' WHERE transaction_id = %s",
                            (transaction_id,)
                        )

                        if credits_to_grant is not None and credits_to_grant > 0:
                            cursor.execute(
                                "UPDATE UserInfo SET interviews_remaining = COALESCE(interviews_remaining, 0) + %s WHERE user_id = %s",
                                (credits_to_grant, user_id)
                            )

                        conn.commit()
                        logger.info("Stripe webhook credited: user=%s, credits=%s, txn=%s", user_id, credits_to_grant, transaction_id)
                    else:
                        conn.rollback()
                except Exception:
                    conn.rollback()
                    logger.exception("Stripe webhook DB error for txn=%s", transaction_id)
                    raise HTTPException(status_code=500, detail="Webhook processing failed")
                finally:
                    conn.autocommit = True
                    cursor.close()

    elif event['type'] == 'checkout.session.expired':
        session = event['data']['object']
        transaction_id = session.get('client_reference_id')
        if transaction_id:
            with get_db() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "UPDATE Transactions SET status = 'failed' WHERE transaction_id = %s AND status = 'pending'",
                        (transaction_id,)
                    )
                    conn.commit()
                finally:
                    cursor.close()

    return {"status": "success"}

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
                        "SELECT status, credits_purchased, user_id FROM Transactions WHERE transaction_id = %s FOR UPDATE",
                        (order_id,)
                    )
                    txn = cursor.fetchone()
                    if txn and txn[0] == 'pending':
                        credits_to_grant = txn[1]
                        user_id = txn[2]

                        cursor.execute(
                            "UPDATE Transactions SET status = 'completed' WHERE transaction_id = %s",
                            (order_id,)
                        )

                        if credits_to_grant is not None and credits_to_grant > 0:
                            cursor.execute(
                                "UPDATE UserInfo SET interviews_remaining = COALESCE(interviews_remaining, 0) + %s WHERE user_id = %s",
                                (credits_to_grant, user_id)
                            )

                        conn.commit()
                        logger.info("Razorpay webhook credited: user=%s, credits=%s, order=%s", user_id, credits_to_grant, order_id)
                    else:
                        conn.rollback()
                except Exception:
                    conn.rollback()
                    logger.exception("Razorpay webhook DB error for order=%s", order_id)
                    raise HTTPException(status_code=500, detail="Webhook processing failed")
                finally:
                    conn.autocommit = True
                    cursor.close()

    return {"status": "success"}