"""Proveniência, base territorial e premissas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, utcnow


class DataSource(Base, TimestampMixin):
    """Catálogo de fontes: URL, licença, atribuição, cobertura e limitações."""

    __tablename__ = "data_source"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    publisher: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str] = mapped_column(Text)
    coverage: Mapped[str] = mapped_column(Text)
    reference_date: Mapped[str] = mapped_column(Text)
    update_method: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text)
    reliability: Mapped[str] = mapped_column(String(16), default="média")


class ImportRun(Base):
    """Execução de importação; cada registro importado aponta para a execução que o gerou."""

    __tablename__ = "import_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"), index=True)
    dataset: Mapped[str] = mapped_column(String(128))
    file_name: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    rows_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Region(Base):
    __tablename__ = "region"

    code: Mapped[int] = mapped_column(Integer, primary_key=True)
    abbrev: Mapped[str] = mapped_column(String(4))
    name: Mapped[str] = mapped_column(String(64))


class State(Base):
    __tablename__ = "state"

    code: Mapped[int] = mapped_column(Integer, primary_key=True)
    uf: Mapped[str] = mapped_column(String(2), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    region_code: Mapped[int] = mapped_column(ForeignKey("region.code"))
    area_km2: Mapped[float | None] = mapped_column(Float)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True))
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))


class Municipality(Base):
    __tablename__ = "municipality"

    code: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    state_code: Mapped[int] = mapped_column(ForeignKey("state.code"))
    region_code: Mapped[int] = mapped_column(ForeignKey("region.code"))
    immediate_region_code: Mapped[int | None] = mapped_column(Integer, index=True)
    immediate_region_name: Mapped[str | None] = mapped_column(String(128))
    intermediate_region_code: Mapped[int | None] = mapped_column(Integer, index=True)
    intermediate_region_name: Mapped[str | None] = mapped_column(String(128))
    population: Mapped[int | None] = mapped_column(BigInteger)
    population_year: Mapped[int | None] = mapped_column(Integer)
    gdp_thousand_brl: Mapped[float | None] = mapped_column(Float)
    gdp_year: Mapped[int | None] = mapped_column(Integer)
    area_km2: Mapped[float | None] = mapped_column(Float)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True))
    centroid = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))


class Assumption(Base, TimestampMixin):
    """Premissa paramétrica explícita (velocidades, custos etc.). Nunca é dado observado."""

    __tablename__ = "assumption"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
