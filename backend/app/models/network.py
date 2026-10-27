"""Grafo logístico versionado: cada versão é imutável e reprodutível."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class NetworkVersion(Base):
    __tablename__ = "network_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="building")
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    import_runs: Mapped[list[int]] = mapped_column(JSONB, default=list)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checksum: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)


class NetworkNode(Base):
    __tablename__ = "network_node"
    __table_args__ = (Index("ix_network_node_version_kind", "version_id", "kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("network_version.id", ondelete="CASCADE"), index=True)
    node_idx: Mapped[int] = mapped_column(Integer)
    # junction | municipality | facility
    kind: Mapped[str] = mapped_column(String(16))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    degree: Mapped[int] = mapped_column(Integer, default=0)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))


class NetworkEdge(Base):
    __tablename__ = "network_edge"
    __table_args__ = (Index("ix_network_edge_version_modal", "version_id", "modal"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("network_version.id", ondelete="CASCADE"), index=True)
    edge_idx: Mapped[int] = mapped_column(Integer)
    u: Mapped[int] = mapped_column(Integer)
    v: Mapped[int] = mapped_column(Integer)
    # road | rail | waterway | access | transfer
    modal: Mapped[str] = mapped_column(String(16))
    segment_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    code: Mapped[str | None] = mapped_column(String(64))
    surface: Mapped[str | None] = mapped_column(String(48))
    length_km: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float] = mapped_column(Float)
    time_h: Mapped[float] = mapped_column(Float)
    cost_brl_t: Mapped[float] = mapped_column(Float)
    capacity: Mapped[float | None] = mapped_column(Float)
    attr_source: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    geom = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=True))
