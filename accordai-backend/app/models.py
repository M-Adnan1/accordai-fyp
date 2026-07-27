from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum, Float, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum

class CallStatus(str, enum.Enum):
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class CallDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"

class Client(Base):
    """A tenant (e.g. a car rental company or a restaurant) using the voice AI backend."""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    # Nullable: a tenant created via signup has no Twilio number until one is
    # provisioned. The voice flow simply can't route calls to it yet.
    twilio_number = Column(String, unique=True, index=True, nullable=True)
    system_prompt = Column(Text, nullable=False)
    greeting = Column(Text, nullable=False)
    voice = Column(String, nullable=False, default="Polly.Ruth-Generative")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    calls = relationship("Call", back_populates="client")
    documents = relationship("Document", back_populates="client")
    tools = relationship("ClientTool", back_populates="client")
    users = relationship("User", back_populates="client")


class User(Base):
    """An AccordAI account. One business owner = one account = one tenant.

    email is globally unique — login is email+password only, and the user's
    client_id is the sole source of tenant context for every protected route.
    client_id is deliberately NOT unique at the DB level: signup always creates
    a fresh Client (one-owner-per-tenant is app-level policy), but seed scripts
    may add extra users (e.g. a 'member' role demo account) to one tenant.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)  # stored lowercase
    password_hash = Column(String, nullable=False)                   # bcrypt
    full_name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="admin")           # "admin" | "member"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="users")


class Customer(Base):
    """Tracks unique callers by phone number."""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)           # can be filled later from frontend
    total_calls = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), onupdate=func.now())

    calls = relationship("Call", back_populates="customer")


class Call(Base):
    __tablename__ = "calls"

    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String, unique=True, index=True, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    from_number = Column(String, nullable=False)
    to_number = Column(String, nullable=False)
    direction = Column(Enum(CallDirection), default=CallDirection.INBOUND)
    status = Column(Enum(CallStatus), default=CallStatus.INITIATED)
    duration = Column(Integer, nullable=True)       # seconds
    total_messages = Column(Integer, default=0)     # updated after each exchange
    summary = Column(Text, nullable=True)           # AI-generated after call ends
    satisfaction_rating = Column(Integer, nullable=True)
    resolved = Column(Boolean, default=False)       # was the issue resolved?
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    client = relationship("Client", back_populates="calls")
    customer = relationship("Customer", back_populates="calls")
    messages = relationship("Message", back_populates="call", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(Integer, ForeignKey("calls.id"), nullable=False)
    role = Column(String, nullable=False)          # "user" or "assistant"
    content = Column(Text, nullable=False)
    response_time_ms = Column(Integer, nullable=True)  # how long AI took to respond
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    call = relationship("Call", back_populates="messages")


class Document(Base):
    """Tracks uploaded RAG documents."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    chunk_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    client = relationship("Client", back_populates="documents")


class ClientTool(Base):
    """An external API a client's AI agent may call mid-conversation (e.g. a booking system)."""
    __tablename__ = "client_tools"
    __table_args__ = (UniqueConstraint("client_id", "name", name="uq_client_tool_name"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String, nullable=False)              # snake_case function name, e.g. "reserve_table"
    description = Column(Text, nullable=False)         # tells the LLM WHEN to call this tool
    parameters_schema = Column(JSON, nullable=False)   # full JSON Schema: type/properties/required
    endpoint_url = Column(String, nullable=False)
    http_method = Column(String, nullable=False, default="POST")
    auth_type = Column(String, nullable=False, default="none")  # "bearer" | "api_key_header" | "none"
    auth_credential = Column(String, nullable=True)    # Fernet-encrypted; never logged or serialized
    auth_header_name = Column(String, nullable=True)   # header to carry the key for auth_type="api_key_header"
    requires_confirmation = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="tools")


class ToolCallLog(Base):
    """Audit trail: one row per tool execution attempt, success or failure."""
    __tablename__ = "tool_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(Integer, ForeignKey("calls.id"), nullable=False)
    tool_id = Column(Integer, ForeignKey("client_tools.id"), nullable=False)
    arguments = Column(JSON, nullable=False)
    response = Column(JSON, nullable=True)
    success = Column(Boolean, nullable=False)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PendingToolCall(Base):
    """A tool call awaiting the caller's spoken confirmation on the next turn.

    Cross-turn state for the one-webhook-per-utterance voice flow; at most one
    pending action per call (call_id is unique).
    """
    __tablename__ = "pending_tool_calls"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(Integer, ForeignKey("calls.id"), unique=True, nullable=False)
    tool_id = Column(Integer, ForeignKey("client_tools.id"), nullable=False)
    arguments = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())