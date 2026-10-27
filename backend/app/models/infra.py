"""Instalações logísticas e segmentos de infraestrutura de transporte."""

from __future__ import annotations

from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# official  = importado de fonte oficial/pública; somente leitura pela API
# user      = cadastrado/editável pelo usuário (ex.: CDs próprios)
# synthetic = entidade criada para demonstração/simulação; nunca misturada a dados oficiais
RECORD_CLASSES = ("official", "user", "synthetic")


class Facility(Base, TimestampMixin):
    __tablename__ = "facility"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_facility_source_external"),
        CheckConstraint(f"record_class IN {RECORD_CLASSES}", name="record_class"),
        Index("ix_facility_category_uf", "category", "uf"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.id"), index=True)
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))
    record_class: Mapped[str] = mapped_column(String(16), default="official", index=True)

    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(48), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(128))
    modal: Mapped[str] = mapped_column(String(24), index=True)
    operator: Mapped[str | None] = mapped_column(String(255))
    capacity_value: Mapped[float | None] = mapped_column(Float)
    capacity_unit: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text)
    municipality_code: Mapped[int | None] = mapped_column(Integer, index=True)
    municipality_name: Mapped[str | None] = mapped_column(String(128))
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    reliability: Mapped[str] = mapped_column(String(16), default="média")
    limitations: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(String(64))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))


class InfraSegment(Base, TimestampMixin):
    """Trecho de infraestrutura linear (rodovia, ferrovia, hidrovia) tal como importado."""

    __tablename__ = "infra_segment"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_segment_source_external"),
        CheckConstraint(f"record_class IN {RECORD_CLASSES}", name="record_class"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.id"), index=True)
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))
    record_class: Mapped[str] = mapped_column(String(16), default="official")
    modal: Mapped[str] = mapped_column(String(24), index=True)
    code: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    jurisdiction: Mapped[str | None] = mapped_column(String(32))
    surface: Mapped[str | None] = mapped_column(String(48))
    situation: Mapped[str | None] = mapped_column(String(64))
    uf: Mapped[str | None] = mapped_column(String(8), index=True)
    length_km: Mapped[float] = mapped_column(Float)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    geom = mapped_column(Geometry("MULTILINESTRING", srid=4326, spatial_index=True))
