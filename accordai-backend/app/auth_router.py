"""Signup, login, and current-user endpoints.

Business model: one owner account = one tenant. Signup atomically creates a
new Client (no Twilio number yet) plus its first user with role "admin".
Login is email + password only; email is globally unique.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.security import hash_password, verify_password, create_access_token
import app.crud as crud

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
    "You are a helpful customer service assistant for {business_name}. "
    "Keep responses brief and conversational (1-3 sentences). "
    "Be friendly, professional, and helpful."
)
DEFAULT_GREETING_TEMPLATE = (
    "Thank you for calling {business_name}! How can I help you today?"
)


class SignupRequest(BaseModel):
    business_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    # bcrypt ignores bytes past 72; cap explicitly rather than truncate silently
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "client_id": user.client_id,
    }


def _auth_response(user: User, client_name: str) -> dict:
    return {
        "access_token": create_access_token(user.id, user.client_id, user.role),
        "token_type": "bearer",
        "user": {**_serialize_user(user), "client_name": client_name},
    }


@router.post("/signup", status_code=201)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    """Create a new tenant and its owner account, and log them in."""
    existing = await crud.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    client = await crud.create_client(
        db,
        name=body.business_name,
        system_prompt=DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(business_name=body.business_name),
        greeting=DEFAULT_GREETING_TEMPLATE.format(business_name=body.business_name),
    )
    try:
        user = await crud.create_user(
            db,
            client_id=client.id,
            email=body.email,
            password_hash=hash_password(body.password),
            full_name=body.full_name,
            role="admin",
        )
    except IntegrityError:
        # Unique-email race between the check above and the insert.
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    logger.info(f"New tenant '{body.business_name}' (client_id={client.id}) signed up.")
    return _auth_response(user, client.name)


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await crud.get_user_by_email(db, body.email)
    # Same error for unknown email and wrong password — don't leak which.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="This account has been deactivated.")

    client = await crud.get_client(db, user.client_id)
    return _auth_response(user, client.name if client else "")


@router.get("/me")
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client = await crud.get_client(db, user.client_id)
    return {**_serialize_user(user), "client_name": client.name if client else ""}  