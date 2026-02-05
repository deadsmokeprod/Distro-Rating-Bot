from datetime import datetime
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inn: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_by_admin_tg_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    users = relationship("User", back_populates="org")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("organizations.id"))
    registered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    payout_details: Mapped[str | None] = mapped_column(Text)

    org = relationship("Organization", back_populates="users")


class ErpSale(Base):
    __tablename__ = "erp_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    month_key: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)
    operation_type: Mapped[str | None] = mapped_column(String)
    product_name: Mapped[str | None] = mapped_column(String)
    volume_total: Mapped[str] = mapped_column(String, nullable=False)
    volume_partial: Mapped[str | None] = mapped_column(String)
    seller_inn: Mapped[str] = mapped_column(String, nullable=False)
    seller_name: Mapped[str | None] = mapped_column(String)
    buyer_inn: Mapped[str | None] = mapped_column(String)
    buyer_name: Mapped[str | None] = mapped_column(String)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SaleConfirmation(Base):
    __tablename__ = "sale_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(Integer, ForeignKey("erp_sales.id"), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    org_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("organizations.id"))
    curator_admin_tg_id: Mapped[int | None] = mapped_column(Integer)
    subject: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    thread_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    close_reason: Mapped[str | None] = mapped_column(String)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("support_tickets.id"))
    direction: Mapped[str] = mapped_column(String)
    msg_type: Mapped[str] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int | None] = mapped_column(Integer)
    role: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    meta_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


__all__ = [
    "Base",
    "Organization",
    "User",
    "ErpSale",
    "SaleConfirmation",
    "SupportTicket",
    "SupportMessage",
    "AuditLog",
]
