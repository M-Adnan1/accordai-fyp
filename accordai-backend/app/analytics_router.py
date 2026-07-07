from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.crud import get_dashboard_analytics
from app.models import Call, Customer
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

router = APIRouter()

@router.get("/dashboard")
async def dashboard_analytics(db: AsyncSession = Depends(get_db)):
    """Main analytics endpoint for the dashboard."""
    return await get_dashboard_analytics(db)

@router.get("/calls")
async def list_calls(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """Paginated call history for the dashboard table."""
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.customer))
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
    db: AsyncSession = Depends(get_db)
):
    """Full conversation transcript for a specific call."""
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.messages), selectinload(Call.customer))
        .where(Call.call_sid == call_sid)
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