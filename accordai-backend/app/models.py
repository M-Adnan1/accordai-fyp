from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum, Float, Boolean
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
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    chunk_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)