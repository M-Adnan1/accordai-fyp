"""Account/tenant settings endpoints for the authenticated user.

Account identity lives at /auth/me; this router covers the tenant record
(Twilio number, webhook info) and password changes. The voice webhook URL is
static and shared by all tenants — incoming calls are routed to a tenant by
the Twilio number that was dialed (crud.get_client_by_number), so pointing a
number's webhook here plus saving that number below is all a tenant needs.
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import User
from app.security import hash_password, verify_password
import app.crud as crud

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_e164(raw: str) -> str:
    """Strip common formatting and convert an international 00-prefix to +.

    Deliberately does NOT guess a country code: a number without one is
    ambiguous, so '+' is required after normalization.
    """
    s = re.sub(r"[\s\-\.\(\)]", "", raw or "")
    if s.startswith("00"):
        s = "+" + s[2:]
    return s


def _serialize_tenant(client) -> dict:
    return {
        "id": client.id,
        "name": client.name,
        "twilio_number": client.twilio_number,
        "voice": client.voice,
        "created_at": client.created_at,
        "webhook_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/voice/incoming",
    }


class TwilioNumberUpdate(BaseModel):
    twilio_number: Optional[str] = None  # null clears the number


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


@router.get("/tenant")
async def get_tenant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The authenticated user's tenant record (plus the static webhook URL)."""
    client = await crud.get_client(db, user.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return _serialize_tenant(client)


@router.patch("/twilio-number")
async def update_twilio_number(
    body: TwilioNumberUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set, replace, or clear (null) the tenant's Twilio number.

    Takes effect on the next incoming call — /voice/incoming resolves the
    tenant by dialed number on every call.
    """
    client = await crud.get_client(db, user.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    number = body.twilio_number
    if number is not None:
        number = normalize_e164(number)
        if not E164_PATTERN.match(number):
            raise HTTPException(
                status_code=422,
                detail="Number must be in E.164 format: '+' followed by country code and "
                       "digits (8-15 total), e.g. +13526236826.",
            )

    try:
        client = await crud.set_client_twilio_number(db, client, number)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This Twilio number is already in use by another account.",
        )

    logger.info(f"Client {client.id} twilio_number set to {number or '(cleared)'} by user {user.id}")
    return _serialize_tenant(client)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    await crud.update_user_password(db, user, hash_password(body.new_password))
    logger.info(f"User {user.id} changed their password.")
    return {"message": "Password updated successfully."}
