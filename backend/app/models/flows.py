"""Fluxos origem-destino, com separação rigorosa por classe de evidência."""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# observed     = registrado em fonte real (ex.: IBGE/CIOT, ANTT, ANTAQ, ANAC)
# modeled      = calculado por modelo do LogiTrace (ex.: alocação ótima de um cenário)
# hypothetical = inserido pelo usuário
# synthetic    = gerado apenas para demonstração
FLOW_CLASSES = ("observed", "modeled", "hypothetical", "synthetic")


class Flow(Base, TimestampMixin):
    __tablename__ = "flow"
    __table_args__ = (
        CheckConstraint(f"flow_class IN {FLOW_CLASSES}", name="flow_class"),
        Index("ix_flow_dataset_value", "dataset", "value"),
        Index("ix_flow_od", "origin_code", "dest_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    flow_class: Mapped[str] = mapped_column(String(16), index=True)
    dataset: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.id"))
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))
    scenario_run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    modal: Mapped[str] = mapped_column(String(16), index=True)
    direction: Mapped[str] = mapped_column(String(16), default="bidirectional")
    origin_code: Mapped[str] = mapped_column(String(32))
    origin_name: Mapped[str] = mapped_column(Text)
    origin_uf: Mapped[str | None] = mapped_column(String(2), index=True)
    dest_code: Mapped[str] = mapped_column(String(32))
    dest_name: Mapped[str] = mapped_column(Text)
    dest_uf: Mapped[str | None] = mapped_column(String(2), index=True)
    origin_lon: Mapped[float] = mapped_column(Float)
    origin_lat: Mapped[float] = mapped_column(Float)
    dest_lon: Mapped[float] = mapped_column(Float)
    dest_lat: Mapped[float] = mapped_column(Float)
    product_group: Mapped[str | None] = mapped_column(Text, index=True)
    product: Mapped[str | None] = mapped_column(Text)
    period: Mapped[str | None] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(48))
    notes: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
