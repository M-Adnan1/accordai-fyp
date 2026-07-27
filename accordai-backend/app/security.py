"""Crypto helpers: tool-credential encryption, password hashing, JWT tokens.

auth_credential values are Fernet-encrypted at rest and must never be logged
or returned in any API response — decrypt only at the moment of use.
Password hashes are bcrypt; JWTs are HS256 access tokens (no refresh tokens —
future work).
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.config import get_settings

settings = get_settings()
_fernet = Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_credential(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_credential(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


# ── Passwords ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# ── JWT access tokens ─────────────────────────────────────

def create_access_token(user_id: int, client_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "client_id": client_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError on bad tokens."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
