from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Organization(Base):
    __tablename__ = "organizations"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    access_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))
    organization_inn: Mapped[str] = mapped_column(ForeignKey("organizations.inn"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    organization = relationship("Organization")


class ErpSale(Base):
    __tablename__ = "erp_sales"
    __table_args__ = (UniqueConstraint("seller_inn", "doc_number", "doc_date", name="uq_sales"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_inn: Mapped[str] = mapped_column(String(12), index=True)
    doc_number: Mapped[str] = mapped_column(String(64))
    doc_date: Mapped[dt.date] = mapped_column(Date)
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    volume_total_l: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class SaleConfirmation(Base):
    __tablename__ = "sale_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("erp_sales.id"), unique=True)
    tg_id: Mapped[int] = mapped_column(ForeignKey("users.tg_id"))
    confirmed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(ForeignKey("users.tg_id"), index=True)
    topic_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
