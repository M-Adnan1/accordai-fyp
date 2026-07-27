from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.crud import get_dashboard_analytics
from app.deps import get_current_user
from app.models import Call, User
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

router = APIRouter()

# Tenant context comes from the authenticated user's client_id on every route.
@router.get("/dashboard")
async def dashboard_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Main analytics endpoint for the authenticated tenant's dashboard."""
    return await get_dashboard_analytics(db, user.client_id)

@router.get("/calls")
async def list_calls(
    skip: int = 0,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    client_id = user.client_id
    """Paginated call history for one client's dashboard table."""
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.customer))
        .where(Call.client_id == client_id)
        .order_by(Call.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    calls = result.scalars().all()
    return [
        {
            "id": c.id,
            "call_sid": c.call_sid,
            "from_number": c.from_number,
            "status": c.status,
            "duration": c.duration,
            "total_messages": c.total_messages,
            "resolved": c.resolved,
            "summary": c.summary,
            "customer_name": c.customer.name if c.customer else None,
            "created_at": c.created_at
        }
        for c in calls
    ]

@router.get("/calls/{call_sid}/transcript")
async def get_transcript(
    call_sid: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    client_id = user.client_id
    """Full conversation transcript for a specific call, scoped to one client."""
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.messages), selectinload(Call.customer))
        .where(Call.call_sid == call_sid, Call.client_id == client_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        return {"error": "Call not found"}

    return {
        "call_sid": call_sid,
        "from_number": call.from_number,
        "status": call.status,
        "duration": call.duration,
        "resolved": call.resolved,
        "summary": call.summary,
        "satisfaction_rating": call.satisfaction_rating,  # add to the call dict in list_calls
        "customer": {
            "phone_number": call.customer.phone_number if call.customer else None,
            "name": call.customer.name if call.customer else None,
            "total_calls": call.customer.total_calls if call.customer else None,
        },
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "response_time_ms": msg.response_time_ms,
                "created_at": msg.created_at
            }
            for msg in call.messages
        ]
    }