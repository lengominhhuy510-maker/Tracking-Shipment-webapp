"""10 DB models — Spec §4.1-4.8 + IC§0.2 (env_conditions, processed_emails).

Rules (IC§2.1): SQLAlchemy 2.x Mapped[]/mapped_column; enum = TEXT + CHECK
(enums.py); every relationship lazy="raise"; FK children-of-shipments CASCADE,
FK to users RESTRICT (IC§2.4). Mirror pattern: shipments.imo/mmsi/
imo_resolved_via/onboarding_status/onboarding_error are copies of the active
leg — written only via resolve_leg() (Spec §4.1 note).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import enums
from app.db.base import Base

# jsonb on Postgres, plain JSON on SQLite (unit tests)
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bl_number: Mapped[str] = mapped_column(Text)
    container_no: Mapped[str] = mapped_column(Text)
    incoterm: Mapped[str] = mapped_column(Text)
    shipment_direction: Mapped[str] = mapped_column(Text)
    carrier: Mapped[str] = mapped_column(Text)
    vessel_name: Mapped[str] = mapped_column(Text)
    imo: Mapped[str | None] = mapped_column(Text)
    imo_resolved_via: Mapped[str | None] = mapped_column(Text)
    mmsi: Mapped[str | None] = mapped_column(Text)
    voyage_no: Mapped[str | None] = mapped_column(Text)
    pol: Mapped[str] = mapped_column(Text)
    pod: Mapped[str] = mapped_column(Text)
    eta_original: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eta_original_source: Mapped[str | None] = mapped_column(Text)
    eta_current: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    atd: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=text("'new'"))
    shipment_type: Mapped[str] = mapped_column(Text, server_default=text("'direct'"))
    onboarding_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    onboarding_error: Mapped[str | None] = mapped_column(Text)
    monitoring_mode: Mapped[str] = mapped_column(Text)
    current_lat: Mapped[float | None] = mapped_column(Double)
    current_lon: Mapped[float | None] = mapped_column(Double)
    current_sog: Mapped[float | None] = mapped_column(Double)
    current_cog: Mapped[float | None] = mapped_column(Double)
    position_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    eta_history: Mapped[list["EtaHistory"]] = relationship(
        back_populates="shipment", lazy="raise", passive_deletes=True
    )
    trail_points: Mapped[list["VesselTrail"]] = relationship(
        back_populates="shipment", lazy="raise", passive_deletes=True
    )
    proposals: Mapped[list["AgentProposal"]] = relationship(
        back_populates="shipment", lazy="raise", passive_deletes=True
    )
    research_findings: Mapped[list["ResearchFinding"]] = relationship(
        back_populates="shipment", lazy="raise", passive_deletes=True
    )
    legs: Mapped[list["ShipmentLeg"]] = relationship(
        back_populates="shipment", lazy="raise", passive_deletes=True
    )
    env_conditions: Mapped["EnvConditions | None"] = relationship(
        back_populates="shipment", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(enums.check_in("incoterm", enums.INCOTERMS), name="ck_shipments_incoterm"),
        CheckConstraint(
            enums.check_in("shipment_direction", enums.SHIPMENT_DIRECTION),
            name="ck_shipments_shipment_direction",
        ),
        CheckConstraint(
            enums.check_in("monitoring_mode", enums.MONITORING_MODE),
            name="ck_shipments_monitoring_mode",
        ),
        CheckConstraint(
            enums.check_in("shipment_type", enums.SHIPMENT_TYPE), name="ck_shipments_shipment_type"
        ),
        CheckConstraint(enums.check_in("status", enums.SHIPMENT_STATUS), name="ck_shipments_status"),
        CheckConstraint(
            enums.check_in("onboarding_status", enums.ONBOARDING_STATUS),
            name="ck_shipments_onboarding_status",
        ),
        CheckConstraint(
            enums.check_in("onboarding_error", enums.ONBOARDING_ERROR),
            name="ck_shipments_onboarding_error",
        ),
        CheckConstraint(
            enums.check_in("imo_resolved_via", enums.IMO_RESOLVED_VIA),
            name="ck_shipments_imo_resolved_via",
        ),
        CheckConstraint(
            enums.check_in("eta_original_source", enums.ETA_ORIGINAL_SOURCE),
            name="ck_shipments_eta_original_source",
        ),
        Index("ix_shipments_status", "status"),
        Index("ix_shipments_onboarding", "onboarding_status"),
        Index(
            "ix_shipments_mmsi",
            "mmsi",
            postgresql_where=text("mmsi IS NOT NULL"),
            sqlite_where=text("mmsi IS NOT NULL"),
        ),
    )


class EtaHistory(Base):
    __tablename__ = "eta_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    eta_value: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text)
    deviation_pct: Mapped[float | None] = mapped_column(Double)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    shipment: Mapped["Shipment"] = relationship(back_populates="eta_history", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            enums.check_in("source", enums.ETA_HISTORY_SOURCE), name="ck_eta_history_source"
        ),
        Index("ix_etahist_shipment_time", "shipment_id", "recorded_at"),
    )


class VesselTrail(Base):
    __tablename__ = "vessel_trail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    sog: Mapped[float | None] = mapped_column(Double)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    shipment: Mapped["Shipment"] = relationship(back_populates="trail_points", lazy="raise")

    __table_args__ = (Index("ix_trail_shipment_time", "shipment_id", "recorded_at"),)


class AgentProposal(Base):
    __tablename__ = "agent_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE")
    )
    source_email_id: Mapped[str] = mapped_column(Text)
    extracted_json: Mapped[dict | None] = mapped_column(JSONVariant)
    proposed_action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    shipment: Mapped["Shipment | None"] = relationship(back_populates="proposals", lazy="raise")
    decider: Mapped["User | None"] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint(
            enums.check_in("status", enums.PROPOSAL_STATUS), name="ck_agent_proposals_status"
        ),
        Index(
            "ix_proposals_status",
            "status",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index(
            "uq_proposals_email_shipment",
            "source_email_id",
            "shipment_id",
            unique=True,
            postgresql_where=text("shipment_id IS NOT NULL"),
            sqlite_where=text("shipment_id IS NOT NULL"),
        ),
    )


class ResearchFinding(Base):
    __tablename__ = "research_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    route_key: Mapped[str | None] = mapped_column(Text)
    event: Mapped[str] = mapped_column(Text)
    relevance: Mapped[str] = mapped_column(Text)
    route_impact: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)
    sources: Mapped[list | None] = mapped_column(JSONVariant)
    verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    shipment: Mapped["Shipment"] = relationship(back_populates="research_findings", lazy="raise")
    verifier: Mapped["User | None"] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint(
            enums.check_in("relevance", enums.RESEARCH_LEVEL), name="ck_findings_relevance"
        ),
        CheckConstraint(
            enums.check_in("confidence", enums.RESEARCH_LEVEL), name="ck_findings_confidence"
        ),
        Index("ix_findings_route_time", "route_key", "created_at"),
    )


class VesselRegistry(Base):
    __tablename__ = "vessel_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vessel_name: Mapped[str] = mapped_column(Text)
    imo: Mapped[str] = mapped_column(Text)
    mmsi: Mapped[str | None] = mapped_column(Text)
    resolved_via: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            enums.check_in("resolved_via", enums.REGISTRY_RESOLVED_VIA),
            name="ck_registry_resolved_via",
        ),
        Index("ix_registry_name", "vessel_name"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    provider_sub: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default=text("'user'"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(enums.check_in("provider", enums.USER_PROVIDER), name="ck_users_provider"),
        CheckConstraint(enums.check_in("role", enums.USER_ROLE), name="ck_users_role"),
        Index("uq_users_provider_sub", "provider", "provider_sub", unique=True),
    )


class ShipmentLeg(Base):
    __tablename__ = "shipment_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    leg_no: Mapped[int] = mapped_column(Integer)
    vessel_name: Mapped[str] = mapped_column(Text)
    voyage_no: Mapped[str | None] = mapped_column(Text)
    imo: Mapped[str | None] = mapped_column(Text)
    mmsi: Mapped[str | None] = mapped_column(Text)
    imo_resolved_via: Mapped[str | None] = mapped_column(Text)
    pol: Mapped[str] = mapped_column(Text)
    pod: Mapped[str] = mapped_column(Text)
    onboarding_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    onboarding_error: Mapped[str | None] = mapped_column(Text)
    is_active_leg: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    shipment: Mapped["Shipment"] = relationship(back_populates="legs", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            enums.check_in("onboarding_status", enums.ONBOARDING_STATUS),
            name="ck_legs_onboarding_status",
        ),
        CheckConstraint(
            enums.check_in("onboarding_error", enums.ONBOARDING_ERROR),
            name="ck_legs_onboarding_error",
        ),
        CheckConstraint(
            enums.check_in("imo_resolved_via", enums.IMO_RESOLVED_VIA),
            name="ck_legs_imo_resolved_via",
        ),
        # DB enforces "only 1 active leg per shipment" — partial unique index (IC§2.3)
        Index(
            "uq_legs_one_active",
            "shipment_id",
            unique=True,
            postgresql_where=text("is_active_leg"),
            sqlite_where=text("is_active_leg"),
        ),
        Index("ix_legs_shipment", "shipment_id"),
    )


class EnvConditions(Base):
    __tablename__ = "env_conditions"

    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), primary_key=True
    )
    wind_speed_kn: Mapped[float | None] = mapped_column(Double)
    wave_height_m: Mapped[float | None] = mapped_column(Double)
    current_speed_kn: Mapped[float | None] = mapped_column(Double)
    current_direction_deg: Mapped[float | None] = mapped_column(Double)
    weather_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tide_extremes: Mapped[list | None] = mapped_column(JSONVariant)
    tide_station_name: Mapped[str | None] = mapped_column(Text)
    tide_station_distance_km: Mapped[float | None] = mapped_column(Double)
    tide_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    shipment: Mapped["Shipment"] = relationship(back_populates="env_conditions", lazy="raise")


class ProcessedEmail(Base):
    __tablename__ = "processed_emails"

    message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    imap_uid: Mapped[int | None] = mapped_column(BigInteger)
    imap_folder: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    unmatched_containers: Mapped[list | None] = mapped_column(JSONVariant)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    seen_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            enums.check_in("outcome", enums.EMAIL_OUTCOME), name="ck_processed_emails_outcome"
        ),
    )
