from fastapi import APIRouter, Depends, HTTPException, status, Query, Response, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Optional
import bcrypt
import jwt
import uuid
import os
import logging
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from database import get_db, transaction
from config import settings
from redis_client import get_redis_client

router = APIRouter(tags=["auth"])
security = HTTPBearer(auto_error=False)
logger = logging.getLogger("auth")

VERIFICATION_LINK_EXPIRY_HOURS = 24
COOKIE_NAME = "interai_session"

PASSWORD_MIN_LENGTH = 8
PASSWORD_PATTERN = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{}|;:\'",.<>?/`~\\])'
)

def _validate_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long")
    if not PASSWORD_PATTERN.search(password):
        raise ValueError(
            "Password must contain at least one uppercase letter, "
            "one lowercase letter, one digit, and one special character"
        )
    return password

def send_verification_email(to_email: str, token: str) -> bool:
    smtp_email = settings.SMTP_EMAIL
    smtp_password = settings.SMTP_PASSWORD

    if not smtp_email or not smtp_password:
        return False

    verify_url = f"{settings.API_BASE_URL}/auth/verify-email?token={token}"

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg["Subject"] = "InterAI — Verify Your Email"

    body = f"""
    <html>
    <body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 20px;">
            <tr><td align="center">
                <table width="480" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
                    <tr><td style="padding:32px 32px 0;">
                        <p style="margin:0;font-size:18px;font-weight:600;color:#18181b;">InterAI</p>
                    </td></tr>
                    <tr><td style="padding:24px 32px;">
                        <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#3f3f46;">Hi there,</p>
                        <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#3f3f46;">Thanks for signing up. Please confirm your email address to get started.</p>
                        <table cellpadding="0" cellspacing="0" style="margin:0 0 24px">
                            <tr><td style="background:#18181b;border-radius:6px;padding:12px 28px;">
                                <a href="{verify_url}" style="color:#ffffff;font-size:14px;font-weight:500;text-decoration:none;display:inline-block;">Verify email address</a>
                            </td></tr>
                        </table>
                        <p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#71717a;">Or paste this link into your browser:</p>
                        <p style="margin:0 0 24px;font-size:12px;line-height:1.5;color:#3b82f6;word-break:break-all;">{verify_url}</p>
                        <p style="margin:0;font-size:13px;line-height:1.5;color:#a1a1aa;">This link expires in {VERIFICATION_LINK_EXPIRY_HOURS} hours. If you didn't create an account, you can safely ignore this email.</p>
                    </td></tr>
                    <tr><td style="padding:20px 32px;border-top:1px solid #f4f4f5;">
                        <p style="margin:0;font-size:12px;color:#a1a1aa;">InterAI &mdash; AI Interview Practice</p>
                    </td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """
    msg.attach(MIMEText(body, "html"))

    try:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        logger.exception("Failed to send verification email")
        return False

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError("Invalid email address")
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return _validate_password_strength(v)

class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError("Invalid email address")
        return v.lower().strip()

class GoogleAuthRequest(BaseModel):
    google_token: str

class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        return v.lower().strip()

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return _validate_password_strength(v)

class AuthResponse(BaseModel):
    token: str
    user_id: str
    email: str
    name: str
    interviews_remaining: int
    is_admin: bool = False
    message: str


def _get_user_flags(user_id: str) -> Dict[str, Any]:
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT full_name, interviews_remaining, is_admin
                FROM UserInfo
                WHERE user_id = %s
                """,
                (user_id,)
            )
            row = cursor.fetchone()
            return {
                "name": row[0] if row and row[0] else "User",
                "interviews_remaining": row[1] if row and row[1] is not None else settings.FREE_CREDITS_ON_SIGNUP,
                "is_admin": bool(row[2]) if row else False,
            }
        finally:
            cursor.close()

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(plain_bytes, hashed_bytes)

async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)

async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)

def _get_token_version(user_id: str) -> int:
    redis_client = get_redis_client()
    if not redis_client:
        return 1
    try:
        version = redis_client.get(f"token_version:{user_id}")
        return int(version) if version else 1
    except Exception:
        return 1

def _increment_token_version(user_id: str) -> int:
    redis_client = get_redis_client()
    if not redis_client:
        return 1
    try:
        key = f"token_version:{user_id}"
        new_version = redis_client.incr(key)
        return int(new_version)
    except Exception:
        return 1

def create_jwt_token(user_id: str, email: str) -> str:
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=settings.JWT_EXPIRATION_DAYS)
    token_version = _get_token_version(user_id)

    payload = {
        "user_id": user_id,
        "email": email,
        "token_version": token_version,
        "iat": issued_at,
        "exp": expires_at
    }

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )

        user_id = payload.get("user_id")
        token_version = payload.get("token_version", 1)
        current_version = _get_token_version(user_id)

        if token_version < current_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked"
            )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

def verify_google_token(google_token: str) -> Dict[str, Any]:
    try:
        request_adapter = google_requests.Request()
        id_info = google_id_token.verify_oauth2_token(
            google_token,
            request_adapter,
            settings.GOOGLE_CLIENT_ID
        )

        audience = id_info.get("aud")
        if audience != settings.GOOGLE_CLIENT_ID:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token audience"
            )

        return id_info

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to verify Google ID token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token"
        )

def _set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_EXPIRATION_DAYS * 86400,
        path="/",
        domain=settings.COOKIE_DOMAIN,
    )

def _clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
        domain=settings.COOKIE_DOMAIN,
    )

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    token = None

    if credentials:
        token = credentials.credentials

    if not token:
        token = request.cookies.get(COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    payload = decode_token(token)
    return payload


async def get_current_user_context(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    flags = _get_user_flags(current_user["user_id"])
    return {
        **current_user,
        "name": flags["name"],
        "interviews_remaining": flags["interviews_remaining"],
        "is_admin": flags["is_admin"],
    }


async def get_current_admin(
    current_user: Dict[str, Any] = Depends(get_current_user_context),
) -> Dict[str, Any]:
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

def _check_login_rate_limit(email: str):
    redis_client = get_redis_client()
    if not redis_client:
        return

    key = f"login_attempts:{email}"
    try:
        attempts = redis_client.get(key)
        if attempts and int(attempts) >= settings.LOGIN_MAX_ATTEMPTS:
            ttl = redis_client.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Try again in {max(ttl, 1)} seconds.",
                headers={"Retry-After": str(max(ttl, 1))}
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to check login rate limit")

def _record_failed_login(email: str):
    redis_client = get_redis_client()
    if not redis_client:
        return

    key = f"login_attempts:{email}"
    try:
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.LOGIN_LOCKOUT_SECONDS)
        pipe.execute()
    except Exception:
        logger.exception("Failed to record failed login attempt")

def _clear_login_attempts(email: str):
    redis_client = get_redis_client()
    if not redis_client:
        return

    try:
        redis_client.delete(f"login_attempts:{email}")
    except Exception:
        pass

@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED
)
async def signup(request: SignupRequest, response: Response):
    with get_db() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                "SELECT user_id, is_verified FROM Login WHERE email = %s",
                (request.email,)
            )

            existing = cursor.fetchone()

            if existing and existing[1]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered and verified"
                )

            verification_token = str(uuid.uuid4())
            token_expiry = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_LINK_EXPIRY_HOURS)

            if existing and not existing[1]:
                with transaction(connection):
                    cursor.execute(
                        """UPDATE Login SET verification_token = %s, token_expiry = %s
                           WHERE email = %s""",
                        (verification_token, token_expiry, request.email)
                    )

                send_verification_email(request.email, verification_token)
                logger.info("Resent verification email: %s", request.email)

                return AuthResponse(**{
                    "token": "",
                    "user_id": existing[0],
                    "email": request.email,
                    "name": request.name,
                    "interviews_remaining": 0,
                    "is_admin": False,
                    "message": "Verification link resent. Please check your email."
                })

            user_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            password_hash = await hash_password_async(request.password)

            with transaction(connection):
                cursor.execute(
                    """
                    INSERT INTO Login (
                        user_id,
                        email,
                        password,
                        auth_provider,
                        date_created,
                        is_verified,
                        verification_token,
                        token_expiry
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, request.email, password_hash, 'local', now, False, verification_token, token_expiry)
                )

                cursor.execute(
                    """
                    INSERT INTO UserInfo (
                        user_id,
                        full_name,
                        mock_interview_count,
                        practice_interview_count,
                        interviews_remaining,
                        date_created
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, request.name, 0, 0, settings.FREE_CREDITS_ON_SIGNUP, now)
                )

            send_verification_email(request.email, verification_token)
            logger.info("New user signed up, verification email sent: %s", request.email)

            return AuthResponse(**{
                "token": "",
                "user_id": user_id,
                "email": request.email,
                "name": request.name,
                "interviews_remaining": 0,
                "is_admin": False,
                "message": "Account created! Please check your email to verify your account."
            })

        except HTTPException:
            raise

        except Exception as e:
            logger.exception("Signup failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Signup failed. Please try again later."
            )

        finally:
            cursor.close()

@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, response: Response):
    _check_login_rate_limit(request.email)

    with get_db() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                "SELECT user_id, password, is_verified, auth_provider FROM Login WHERE email = %s",
                (request.email,)
            )

            row = cursor.fetchone()

            if not row:
                await hash_password_async(os.urandom(16).hex())
                _record_failed_login(request.email)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password"
                )

            user_id, stored_hash, is_verified, auth_provider = row

            if auth_provider == 'google' or stored_hash is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This account uses Google Sign-In. Please log in with Google."
                )

            if not await verify_password_async(request.password, stored_hash):
                _record_failed_login(request.email)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password"
                )

            if not is_verified:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Email not verified. Please check your inbox and click the verification link."
                )

            _clear_login_attempts(request.email)

            flags = _get_user_flags(user_id)
            name = flags["name"]
            interviews_remaining = flags["interviews_remaining"]
            is_admin = flags["is_admin"]

            token = create_jwt_token(user_id, request.email)
            _set_auth_cookie(response, token)

            logger.info("User logged in: %s", request.email)

            return AuthResponse(**{
                "token": "",
                "user_id": user_id,
                "email": request.email,
                "name": name,
                "interviews_remaining": interviews_remaining,
                "is_admin": is_admin,
                "message": "Login successful"
            })

        finally:
            cursor.close()

@router.post("/google", response_model=AuthResponse)
async def google_auth(request: GoogleAuthRequest, response: Response):
    with get_db() as connection:
        cursor = connection.cursor()
        email = None

        try:
            id_info = verify_google_token(request.google_token)

            email = id_info.get("email")
            name = id_info.get("name", "User")
            google_user_id = id_info.get("sub")

            if not email or not google_user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Google token data"
                )

            cursor.execute(
                "SELECT user_id FROM Login WHERE email = %s",
                (email,)
            )

            row = cursor.fetchone()
            now = datetime.now(timezone.utc)

            if row:
                user_id = row[0]
                flags = _get_user_flags(user_id)
                name = flags["name"] or name
                interviews_remaining = flags["interviews_remaining"]
                is_admin = flags["is_admin"]

                message = "Login successful"
                logger.info("Google login: %s", email)

            else:
                user_id = str(uuid.uuid4())

                with transaction(connection):
                    cursor.execute(
                        """
                        INSERT INTO Login (
                            user_id,
                            email,
                            password,
                            auth_provider,
                            google_id,
                            date_created,
                            is_verified
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, email, None, 'google', google_user_id, now, True)
                    )

                    cursor.execute(
                        """
                        INSERT INTO UserInfo (
                            user_id,
                            full_name,
                            mock_interview_count,
                            practice_interview_count,
                            interviews_remaining,
                            date_created
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, name, 0, 0, settings.FREE_CREDITS_ON_SIGNUP, now)
                    )

                interviews_remaining = settings.FREE_CREDITS_ON_SIGNUP
                is_admin = False
                message = "Google signup successful"
                logger.info("Google signup: %s", email)

            token = create_jwt_token(user_id, email)
            _set_auth_cookie(response, token)

            return AuthResponse(**{
                "token": "",
                "user_id": user_id,
                "email": email,
                "name": name,
                "interviews_remaining": interviews_remaining,
                "is_admin": is_admin,
                "message": "Login successful" if message == "Login successful" else message
            })

        except HTTPException:
            raise

        except Exception:
            logger.exception("Google auth failed for email=%s", email or 'unknown')
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google authentication failed"
            )

        finally:
            cursor.close()

@router.get("/verify-email")
async def verify_email(token: str = Query(..., description="Email verification token")):
    with get_db() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                "SELECT email FROM Login WHERE verification_token = %s AND token_expiry > %s",
                (token, datetime.now(timezone.utc))
            )

            row = cursor.fetchone()

            if not row:
                return RedirectResponse(url=f"{settings.APP_BASE_URL}?verified=false&error=invalid_or_expired_token")

            email = row[0]

            with transaction(connection):
                cursor.execute(
                    """
                    UPDATE Login
                    SET is_verified = TRUE,
                        verification_token = NULL,
                        token_expiry = NULL
                    WHERE email = %s
                    """,
                    (email,)
                )

            logger.info("Email verified successfully: %s", email)
            return RedirectResponse(url=f"{settings.APP_BASE_URL}?verified=true")

        except Exception:
            logger.exception("Email verification failed")
            return RedirectResponse(url=f"{settings.APP_BASE_URL}?verified=false&error=server_error")

        finally:
            cursor.close()

@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT user_id, auth_provider FROM Login WHERE email = %s", (request.email,))
            user = cursor.fetchone()
            if not user:
                return {"message": "If that email is registered, we have sent a password reset link."}

            if user[1] == 'google':
                return {"message": "If that email is registered, we have sent a password reset link."}

            reset_token = str(uuid.uuid4())
            token_expiry = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_LINK_EXPIRY_HOURS)

            with transaction(connection):
                cursor.execute(
                    """UPDATE Login SET reset_token = %s, reset_token_expiry = %s
                       WHERE email = %s""",
                    (reset_token, token_expiry, request.email)
                )

            smtp_email = settings.SMTP_EMAIL
            smtp_password = settings.SMTP_PASSWORD

            if smtp_email and smtp_password:
                reset_url = f"{settings.APP_BASE_URL}/reset-password?token={reset_token}"
                msg = MIMEMultipart()
                msg["From"] = smtp_email
                msg["To"] = request.email
                msg["Subject"] = "InterAI — Reset Your Password"

                body = f"""
                <html>
                <body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 20px;">
                        <tr><td align="center">
                            <table width="480" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
                                <tr><td style="padding:32px 32px 0;">
                                    <p style="margin:0;font-size:18px;font-weight:600;color:#18181b;">InterAI</p>
                                </td></tr>
                                <tr><td style="padding:24px 32px;">
                                    <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#3f3f46;">Hi there,</p>
                                    <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#3f3f46;">We received a request to reset your password. Click the button below to choose a new one.</p>
                                    <table cellpadding="0" cellspacing="0" style="margin:0 0 24px">
                                        <tr><td style="background:#18181b;border-radius:6px;padding:12px 28px;">
                                            <a href="{reset_url}" style="color:#ffffff;font-size:14px;font-weight:500;text-decoration:none;display:inline-block;">Reset password</a>
                                        </td></tr>
                                    </table>
                                    <p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#71717a;">Or paste this link into your browser:</p>
                                    <p style="margin:0 0 24px;font-size:12px;line-height:1.5;color:#3b82f6;word-break:break-all;">{reset_url}</p>
                                    <p style="margin:0;font-size:13px;line-height:1.5;color:#a1a1aa;">This link expires in {VERIFICATION_LINK_EXPIRY_HOURS} hours. If you didn't request a password reset, you can safely ignore this email.</p>
                                </td></tr>
                                <tr><td style="padding:20px 32px;border-top:1px solid #f4f4f5;">
                                    <p style="margin:0;font-size:12px;color:#a1a1aa;">InterAI &mdash; AI Interview Practice</p>
                                </td></tr>
                            </table>
                        </td></tr>
                    </table>
                </body>
                </html>
                """
                msg.attach(MIMEText(body, "html"))

                def send_email():
                    try:
                        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
                        server.starttls()
                        server.login(smtp_email, smtp_password)
                        server.send_message(msg)
                        server.quit()
                    except Exception as e:
                        logger.exception("Failed to send reset email")

                asyncio.create_task(asyncio.to_thread(send_email))
            else:
                logger.warning("SMTP not configured — password reset email could not be sent for %s", request.email)

            return {"message": "If that email is registered, we have sent a password reset link."}
        except Exception:
            logger.exception("Forgot password failed")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to process request")
        finally:
            cursor.close()

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    with get_db() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT user_id, email FROM Login WHERE reset_token = %s AND reset_token_expiry > %s",
                (request.token, datetime.now(timezone.utc))
            )
            row = cursor.fetchone()

            if not row:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token")

            user_id = row[0]
            email = row[1]
            password_hash = await hash_password_async(request.password)

            with transaction(connection):
                cursor.execute(
                    """UPDATE Login SET password = %s, reset_token = NULL, reset_token_expiry = NULL
                       WHERE email = %s""",
                    (password_hash, email)
                )

            _increment_token_version(user_id)

            return {"message": "Password reset successfully"}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Reset password failed")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to reset password")
        finally:
            cursor.close()

@router.get("/verify")
async def verify_token(current_user: Dict[str, Any] = Depends(get_current_user_context)):
    return {
        "valid": True,
        "user_id": current_user["user_id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "interviews_remaining": current_user["interviews_remaining"],
        "is_admin": current_user["is_admin"],
    }

@router.post("/refresh")
async def refresh_token(
    response: Response,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    token = create_jwt_token(
        current_user["user_id"],
        current_user["email"]
    )
    _set_auth_cookie(response, token)

    return {
        "token": "",
        "message": "Token refreshed"
    }

@router.post("/logout")
async def logout(
    response: Response,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    _increment_token_version(current_user["user_id"])
    _clear_auth_cookie(response)

    return {"message": "Logged out successfully"}
