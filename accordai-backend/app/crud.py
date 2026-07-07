from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func, cast, Date
from app.models import Call, Message, CallStatus, Customer, Document
from typing import List, Optional
import time

# ── Customer ──────────────────────────────────────────────

async def get_or_create_customer(
    db: AsyncSession,
    phone_number: str
) -> Customer:
    result = await db.execute(
        select(Customer).where(Customer.phone_number == phone_number)
    )
    customer = result.scalar_one_or_none()

    if not customer:
        customer = Customer(phone_number=phone_number)
        db.add(customer)
        await db.flush()  # get ID without full commit
    
    customer.total_calls += 1
    customer.last_seen = func.now()
    await db.commit()
    await db.refresh(customer)
    return customer

# ── Calls ─────────────────────────────────────────────────

async def create_call(
    db: AsyncSession,
    call_sid: str,
    from_number: str,
    to_number: str
) -> Call:
    customer = await get_or_create_customer(db, from_number)
    call = Call(
        call_sid=call_sid,
        from_number=from_number,
        to_number=to_number,
        customer_id=customer.id
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call

async def get_call_by_sid(
    db: AsyncSession,
    call_sid: str
) -> Optional[Call]:
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.messages))
        .where(Call.call_sid == call_sid)
    )
    return result.scalar_one_or_none()

async def update_call_status(
    db: AsyncSession,
    call_sid: str,
    status: CallStatus,
    duration: Optional[int] = None,
    summary: Optional[str] = None,
    resolved: Optional[bool] = None
) -> Optional[Call]:
    call = await get_call_by_sid(db, call_sid)
    if call:
        call.status = status
        if duration is not None:
            call.duration = duration
        if summary is not None:
            call.summary = summary
        if resolved is not None:
            call.resolved = resolved
        await db.commit()
        await db.refresh(call)
    return call

async def add_message(
    db: AsyncSession,
    call_sid: str,
    role: str,
    content: str,
    response_time_ms: Optional[int] = None
) -> Message:
    call = await get_call_by_sid(db, call_sid)
    if not call:
        raise ValueError(f"Call not found: {call_sid}")

    message = Message(
        call_id=call.id,
        role=role,
        content=content,
        response_time_ms=response_time_ms
    )
    db.add(message)

    # Keep total_messages count in sync
    call.total_messages += 1
    await db.commit()
    await db.refresh(message)
    return message

async def get_conversation_history(
    db: AsyncSession,
    call_sid: str
) -> List[dict]:
    call = await get_call_by_sid(db, call_sid)
    if not call:
        return []
    return [
        {"role": msg.role, "content": msg.content}
        for msg in call.messages
    ]


async def get_dashboard_analytics(db: AsyncSession) -> dict:
    # Total calls
    total_calls = await db.scalar(select(func.count(Call.id)))

    # Calls by status
    completed = await db.scalar(
        select(func.count(Call.id)).where(Call.status == CallStatus.COMPLETED)
    )
    failed = await db.scalar(
        select(func.count(Call.id)).where(Call.status == CallStatus.FAILED)
    )

    # Average duration (completed calls only)
    avg_duration = await db.scalar(
        select(func.avg(Call.duration)).where(
            Call.status == CallStatus.COMPLETED,
            Call.duration.isnot(None)
        )
    )

    # Total unique customers
    total_customers = await db.scalar(select(func.count(Customer.id)))

    # Resolved rate
    resolved_count = await db.scalar(
        select(func.count(Call.id)).where(Call.resolved == True)
    )

    # Calls per day (last 7 days)
    calls_per_day = await db.execute(
        select(
            cast(Call.created_at, Date).label("date"),
            func.count(Call.id).label("count")
        )
        .group_by(cast(Call.created_at, Date))
        .order_by(cast(Call.created_at, Date).desc())
        .limit(7)
    )
    calls_per_day_data = [
        {"date": str(row.date), "calls": row.count}
        for row in calls_per_day
    ]

    # Avg messages per call
    avg_messages = await db.scalar(select(func.avg(Call.total_messages)))

    # Average satisfaction (only rated calls)
    avg_satisfaction = await db.scalar(
        select(func.avg(Call.satisfaction_rating)).where(
        Call.satisfaction_rating.isnot(None)
        )
    )
    satisfied_count = await db.scalar(
    select(func.count(Call.id)).where(Call.satisfaction_rating == 1)
    )
    rated_count = await db.scalar(
    select(func.count(Call.id)).where(
        Call.satisfaction_rating.isnot(None)
        )
    )
    return {
        "total_calls": total_calls or 0,
        "completed_calls": completed or 0,
        "failed_calls": failed or 0,
        "avg_duration_seconds": round(avg_duration or 0, 1),
        "total_customers": total_customers or 0,
        "resolved_calls": resolved_count or 0,
        "resolution_rate": round((resolved_count / total_calls * 100) if total_calls else 0, 1),
        "avg_messages_per_call": round(avg_messages or 0, 1),
        "calls_per_day": calls_per_day_data,
        # Add to the return dict
        "satisfaction_rate": round((satisfied_count / rated_count * 100) if rated_count else 0, 1),
        "total_rated_calls": rated_count or 0,
    }


async def create_document_record(
    db: AsyncSession,
    filename: str,
    file_type: str,
    chunk_count: int
) -> Document:
    doc = Document(
        filename=filename,
        file_type=file_type,
        chunk_count=chunk_count
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc

async def get_all_documents(db: AsyncSession) -> List[Document]:
    result = await db.execute(
        select(Document).where(Document.is_active == True)
    )
    return result.scalars().all()

async def deactivate_document(db: AsyncSession, filename: str) -> bool:
    result = await db.execute(
        select(Document).where(Document.filename == filename)
    )
    doc = result.scalar_one_or_none()
    if doc:
        doc.is_active = False
        await db.commit()
        return True
    return False

async def update_call_rating(
    db: AsyncSession,
    call_sid: str,
    rating: int
) -> Optional[Call]:
    call = await get_call_by_sid(db, call_sid)
    if call:
        call.satisfaction_rating = rating
        await db.commit()
        await db.refresh(call)
    return call