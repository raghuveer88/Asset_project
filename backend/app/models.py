from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Property(Base, TimestampMixin):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    property_name: Mapped[str | None] = mapped_column(String(255))
    official_property_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    website_url: Mapped[str | None] = mapped_column(String(1000))
    scrape_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    match_confidence: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)


class RentRollSnapshot(Base):
    __tablename__ = "rent_roll_snapshots"
    __table_args__ = (
        Index("ix_snapshot_property_month", "property_code", "report_month"),
        UniqueConstraint("property_code", "report_month", "source_file", name="uq_snapshot_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    property_name: Mapped[str | None] = mapped_column(String(255))
    report_month: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    as_of_date: Mapped[datetime | None] = mapped_column(Date)
    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    rows: Mapped[list["RentRollRow"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True
    )
    summary_groups: Mapped[list["RentRollSummaryGroup"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True
    )
    charge_summaries: Mapped[list["RentRollChargeSummary"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True
    )
    future_residents: Mapped[list["RentRollFutureResident"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True
    )


class RentRollRow(Base):
    __tablename__ = "rent_roll_rows"
    __table_args__ = (
        Index("ix_rows_property_month", "property_code", "report_month"),
        Index("ix_rows_property_unit", "property_code", "unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("rent_roll_snapshots.id", ondelete="CASCADE"), index=True)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    report_month: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64))
    unit_type: Mapped[str | None] = mapped_column(String(128))
    unit_sqft: Mapped[float | None] = mapped_column(Float(53))
    resident_id: Mapped[str | None] = mapped_column(String(128))
    resident_name: Mapped[str | None] = mapped_column(String(255))
    market_rent: Mapped[float | None] = mapped_column(Float(53))
    charge_code: Mapped[str | None] = mapped_column(String(64))
    charge_amount: Mapped[float | None] = mapped_column(Float(53))
    resident_deposit: Mapped[float | None] = mapped_column(Float(53))
    other_deposit: Mapped[float | None] = mapped_column(Float(53))
    move_in: Mapped[datetime | None] = mapped_column(Date)
    lease_expiration: Mapped[datetime | None] = mapped_column(Date)
    move_out: Mapped[datetime | None] = mapped_column(Date)
    balance: Mapped[float | None] = mapped_column(Float(53))
    occupancy_status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    snapshot: Mapped[RentRollSnapshot] = relationship(back_populates="rows")


class RentRollSummaryGroup(Base):
    __tablename__ = "rent_roll_summary_groups"
    __table_args__ = (
        Index("ix_summary_groups_property_month", "property_code", "report_month"),
        Index("ix_summary_groups_snapshot_group", "snapshot_id", "group_name"),
        UniqueConstraint("snapshot_id", "group_name", name="uq_summary_group_snapshot_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("rent_roll_snapshots.id", ondelete="CASCADE"), index=True)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    report_month: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False)
    original_label: Mapped[str | None] = mapped_column(String(255))
    square_footage: Mapped[float | None] = mapped_column(Float(53))
    market_rent: Mapped[float | None] = mapped_column(Float(53))
    lease_charges: Mapped[float | None] = mapped_column(Float(53))
    security_deposit: Mapped[float | None] = mapped_column(Float(53))
    other_deposits: Mapped[float | None] = mapped_column(Float(53))
    unit_count: Mapped[int | None] = mapped_column(Integer)
    unit_occupancy_pct: Mapped[float | None] = mapped_column(Float(53))
    sqft_occupied_pct: Mapped[float | None] = mapped_column(Float(53))
    balance: Mapped[float | None] = mapped_column(Float(53))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    snapshot: Mapped[RentRollSnapshot] = relationship(back_populates="summary_groups")


class RentRollChargeSummary(Base):
    __tablename__ = "rent_roll_charge_summaries"
    __table_args__ = (
        Index("ix_charge_summaries_property_month", "property_code", "report_month"),
        Index("ix_charge_summaries_snapshot_code", "snapshot_id", "charge_code"),
        UniqueConstraint("snapshot_id", "scope", "charge_code", name="uq_charge_summary_snapshot_scope_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("rent_roll_snapshots.id", ondelete="CASCADE"), index=True)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    report_month: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(128), default="current_notice_residents_only", nullable=False)
    charge_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float | None] = mapped_column(Float(53))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    snapshot: Mapped[RentRollSnapshot] = relationship(back_populates="charge_summaries")


class RentRollFutureResident(Base):
    __tablename__ = "rent_roll_future_residents"
    __table_args__ = (
        Index("ix_future_residents_property_month", "property_code", "report_month"),
        Index("ix_future_residents_property_unit", "property_code", "unit"),
        Index("ix_future_residents_snapshot_unit", "snapshot_id", "unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("rent_roll_snapshots.id", ondelete="CASCADE"), index=True)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    report_month: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64))
    unit_type: Mapped[str | None] = mapped_column(String(128))
    unit_sqft: Mapped[float | None] = mapped_column(Float(53))
    resident_id: Mapped[str | None] = mapped_column(String(128))
    resident_name: Mapped[str | None] = mapped_column(String(255))
    market_rent: Mapped[float | None] = mapped_column(Float(53))
    resident_deposit: Mapped[float | None] = mapped_column(Float(53))
    other_deposit: Mapped[float | None] = mapped_column(Float(53))
    move_in: Mapped[date | None] = mapped_column(Date)
    lease_expiration: Mapped[date | None] = mapped_column(Date)
    move_out: Mapped[date | None] = mapped_column(Date)
    balance: Mapped[float | None] = mapped_column(Float(53))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    snapshot: Mapped[RentRollSnapshot] = relationship(back_populates="future_residents")


class WebsitePage(Base):
    __tablename__ = "website_pages"
    __table_args__ = (
        Index("ix_website_property_url", "property_code", "url", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(700), nullable=False)
    page_title: Mapped[str | None] = mapped_column(String(500))
    local_file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_session_property", "session_id", "property_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    selected_model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_property", "session_id", "property_code", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    property_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[str | None] = mapped_column(String(64))
    tools_used_json: Mapped[str | None] = mapped_column(Text)
    response_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
