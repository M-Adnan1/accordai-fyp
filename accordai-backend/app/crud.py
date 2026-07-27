from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func, cast, Date
from app.models import (
    Call, Message, CallStatus, Customer, Document, Client,
    ClientTool, ToolCallLog, PendingToolCall, User
)
from typing import List, Optional
import time

# ── Clients ───────────────────────────────────────────────

async def get_client_by_number(
    db: AsyncSession,
    twilio_number: str
) -> Optional[Client]:
    """Look up an active client by the Twilio number that was called."""
    result = await db.execute(
        select(Client).where(
            Client.twilio_number == twilio_number,
            Client.is_active == True
        )
    )
    return result.scalar_one_or_none()

async def get_client(
    db: AsyncSession,
    client_id: int
) -> Optional[Client]:
    result = await db.execute(
        select(Client).where(Client.id == client_id)
    )
    return result.scalar_one_or_none()

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
    to_number: str,
    client_id: int
) -> Call:
    customer = await get_or_create_customer(db, from_number)
    call = Call(
        call_sid=call_sid,
        from_number=from_number,
        to_number=to_number,
        customer_id=customer.id,
        client_id=client_id
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
        .options(selectinload(Call.messages), selectinload(Call.client))
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


async def get_dashboard_analytics(db: AsyncSession, client_id: int) -> dict:
    # Total calls
    total_calls = await db.scalar(
        select(func.count(Call.id)).where(Call.client_id == client_id)
    )

    # Calls by status
    completed = await db.scalar(
        select(func.count(Call.id)).where(
            Call.client_id == client_id,
            Call.status == CallStatus.COMPLETED
        )
    )
    failed = await db.scalar(
        select(func.count(Call.id)).where(
            Call.client_id == client_id,
            Call.status == CallStatus.FAILED
        )
    )

    # Average duration (completed calls only)
    avg_duration = await db.scalar(
        select(func.avg(Call.duration)).where(
            Call.client_id == client_id,
            Call.status == CallStatus.COMPLETED,
            Call.duration.isnot(None)
        )
    )

    # Unique customers who have called this client
    total_customers = await db.scalar(
        select(func.count(func.distinct(Call.customer_id))).where(
            Call.client_id == client_id,
            Call.customer_id.isnot(None)
        )
    )

    # Resolved rate
    resolved_count = await db.scalar(
        select(func.count(Call.id)).where(
            Call.client_id == client_id,
            Call.resolved == True
        )
    )

    # Calls per day (last 7 days)
    calls_per_day = await db.execute(
        select(
            cast(Call.created_at, Date).label("date"),
            func.count(Call.id).label("count")
        )
        .where(Call.client_id == client_id)
        .group_by(cast(Call.created_at, Date))
        .order_by(cast(Call.created_at, Date).desc())
        .limit(7)
    )
    calls_per_day_data = [
        {"date": str(row.date), "calls": row.count}
        for row in calls_per_day
    ]

    # Avg messages per call
    avg_messages = await db.scalar(
        select(func.avg(Call.total_messages)).where(Call.client_id == client_id)
    )

    # Average satisfaction (only rated calls)
    avg_satisfaction = await db.scalar(
        select(func.avg(Call.satisfaction_rating)).where(
            Call.client_id == client_id,
            Call.satisfaction_rating.isnot(None)
        )
    )
    satisfied_count = await db.scalar(
        select(func.count(Call.id)).where(
            Call.client_id == client_id,
            Call.satisfaction_rating == 1
        )
    )
    rated_count = await db.scalar(
        select(func.count(Call.id)).where(
            Call.client_id == client_id,
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
    client_id: int,
    filename: str,
    file_type: str,
    chunk_count: int
) -> Document:
    doc = Document(
        client_id=client_id,
        filename=filename,
        file_type=file_type,
        chunk_count=chunk_count
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc

async def get_all_documents(db: AsyncSession, client_id: int) -> List[Document]:
    result = await db.execute(
        select(Document).where(
            Document.client_id == client_id,
            Document.is_active == True
        )
    )
    return result.scalars().all()

async def deactivate_document(db: AsyncSession, client_id: int, filename: str) -> bool:
    result = await db.execute(
        select(Document).where(
            Document.client_id == client_id,
            Document.filename == filename
        )
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

# ── Client tools ──────────────────────────────────────────

async def get_active_tools(db: AsyncSession, client_id: int) -> List[ClientTool]:
    result = await db.execute(
        select(ClientTool).where(
            ClientTool.client_id == client_id,
            ClientTool.is_active == True
        )
    )
    return result.scalars().all()

async def get_tool_by_name(
    db: AsyncSession,
    client_id: int,
    name: str
) -> Optional[ClientTool]:
    result = await db.execute(
        select(ClientTool).where(
            ClientTool.client_id == client_id,
            ClientTool.name == name,
            ClientTool.is_active == True
        )
    )
    return result.scalar_one_or_none()

async def get_tool_by_id(db: AsyncSession, tool_id: int) -> Optional[ClientTool]:
    result = await db.execute(
        select(ClientTool).where(ClientTool.id == tool_id)
    )
    return result.scalar_one_or_none()

async def create_client_tool(
    db: AsyncSession,
    client_id: int,
    name: str,
    description: str,
    parameters_schema: dict,
    endpoint_url: str,
    http_method: str = "POST",
    auth_type: str = "none",
    auth_credential: Optional[str] = None,   # already encrypted by the caller
    auth_header_name: Optional[str] = None,
    requires_confirmation: bool = True
) -> ClientTool:
    tool = ClientTool(
        client_id=client_id,
        name=name,
        description=description,
        parameters_schema=parameters_schema,
        endpoint_url=endpoint_url,
        http_method=http_method,
        auth_type=auth_type,
        auth_credential=auth_credential,
        auth_header_name=auth_header_name,
        requires_confirmation=requires_confirmation
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool

async def update_client_tool(
    db: AsyncSession,
    tool: ClientTool,
    updates: dict            # column name -> new value; auth_credential already encrypted
) -> ClientTool:
    """Apply a partial update to an existing tool and persist it."""
    for field, value in updates.items():
        setattr(tool, field, value)
    await db.commit()
    await db.refresh(tool)
    return tool

async def log_tool_call(
    db: AsyncSession,
    call_id: int,
    tool_id: int,
    arguments: dict,
    response: Optional[dict],
    success: bool,
    error_message: Optional[str] = None
) -> ToolCallLog:
    log = ToolCallLog(
        call_id=call_id,
        tool_id=tool_id,
        arguments=arguments,
        response=response,
        success=success,
        error_message=error_message
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log

# ── Pending tool calls (cross-turn confirmation state) ────

async def get_pending_tool_call(
    db: AsyncSession,
    call_id: int
) -> Optional[PendingToolCall]:
    result = await db.execute(
        select(PendingToolCall).where(PendingToolCall.call_id == call_id)
    )
    return result.scalar_one_or_none()

async def create_pending_tool_call(
    db: AsyncSession,
    call_id: int,
    tool_id: int,
    arguments: dict
) -> PendingToolCall:
    # At most one pending action per call — replace any stale one.
    existing = await get_pending_tool_call(db, call_id)
    if existing:
        await db.delete(existing)
        await db.flush()
    pending = PendingToolCall(call_id=call_id, tool_id=tool_id, arguments=arguments)
    db.add(pending)
    await db.commit()
    await db.refresh(pending)
    return pending

async def delete_pending_tool_call(db: AsyncSession, call_id: int) -> None:
    pending = await get_pending_tool_call(db, call_id)
    if pending:
        await db.delete(pending)
        await db.commit()

# ── Users & auth ──────────────────────────────────────────

async def create_client(
    db: AsyncSession,
    name: str,
    system_prompt: str,
    greeting: str,
) -> Client:
    """Create a tenant with no Twilio number yet (signup flow)."""
    client = Client(name=name, system_prompt=system_prompt, greeting=greeting)
    db.add(client)
    await db.flush()  # assign client.id without committing — signup commits atomically
    return client

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()

async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

async def create_user(
    db: AsyncSession,
    client_id: int,
    email: str,
    password_hash: str,
    full_name: Optional[str] = None,
    role: str = "admin",
) -> User:
    user = User(
        client_id=client_id,
        email=email.lower(),
        password_hash=password_hash,
        full_name=full_name,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def set_client_twilio_number(
    db: AsyncSession,
    client: Client,
    twilio_number: Optional[str],   # already E.164-normalized, or None to clear
) -> Client:
    client.twilio_number = twilio_number
    await db.commit()
    await db.refresh(client)
    return client

async def update_user_password(
    db: AsyncSession,
    user: User,
    password_hash: str,
) -> None:
    user.password_hash = password_hash
    await db.commit()