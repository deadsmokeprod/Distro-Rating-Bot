from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    inn = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_by_admin_tg_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Integer, default=1, nullable=False)

    users = relationship("User", back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, nullable=False)
    role = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    org_id = Column(Integer, ForeignKey("organizations.id"))
    registered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime)
    payout_details = Column(Text)

    organization = relationship("Organization", back_populates="users")


class ErpSale(Base):
    __tablename__ = "erp_sales"

    id = Column(Integer, primary_key=True)
    source_hash = Column(String, unique=True, nullable=False)
    month_key = Column(String, nullable=False)
    period = Column(String, nullable=False)
    operation_type = Column(String)
    product_name = Column(String)
    volume_total = Column(String, nullable=False)
    volume_partial = Column(String)
    seller_inn = Column(String, nullable=False)
    seller_name = Column(String)
    buyer_inn = Column(String)
    buyer_name = Column(String)
    loaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SaleConfirmation(Base):
    __tablename__ = "sale_confirmations"

    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("erp_sales.id"), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    confirmed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("sale_id", name="uq_sale_confirmations_sale_id"),)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    org_id = Column(Integer, ForeignKey("organizations.id"))
    curator_admin_tg_id = Column(Integer)
    subject = Column(String)
    status = Column(String)
    thread_id = Column(Integer, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)
    close_reason = Column(String)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id"))
    direction = Column(String)
    msg_type = Column(String)
    text = Column(Text)
    file_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer)
    role = Column(String)
    action = Column(String)
    meta_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
