"""Cenários, alterações, execuções, otimizações e tarefas assíncronas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, utcnow


class Scenario(Base, TimestampMixin):
    __tablename__ = "scenario"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    # Configuração da avaliação: pares OD de referência, instalações de atendimento, demanda...
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    network_version_id: Mapped[int | None] = mapped_column(ForeignKey("network_version.id"))


class ScenarioChange(Base):
    """Alteração aplicada sobre a base, sem modificá-la (closure, new_facility, capacity, cost, demand)."""

    __tablename__ = "scenario_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenario.id", ondelete="CASCADE"), index=True)
    change_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScenarioRun(Base):
    __tablename__ = "scenario_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenario.id", ondelete="CASCADE"), index=True)
    network_version_id: Mapped[int] = mapped_column(ForeignKey("network_version.id"))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    # Snapshot completo das entradas (config + alterações + premissas) => reprodutibilidade
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    rerun_of: Mapped[int | None] = mapped_column(Integer)


class OptimizationRun(Base):
    __tablename__ = "optimization_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    problem: Mapped[str] = mapped_column(String(48), index=True)
    label: Mapped[str | None] = mapped_column(String(160))
    network_version_id: Mapped[int | None] = mapped_column(ForeignKey("network_version.id"))
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("scenario.id", ondelete="SET NULL"))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    # OPTIMAL | FEASIBLE | HEURISTIC | INFEASIBLE | NOT_SOLVED | ERROR
    solution_quality: Mapped[str | None] = mapped_column(String(24))
    solver: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    objective_value: Mapped[float | None] = mapped_column(Float)
    best_bound: Mapped[float | None] = mapped_column(Float)
    gap: Mapped[float | None] = mapped_column(Float)
    solve_time_ms: Mapped[float | None] = mapped_column(Float)
    constraints: Mapped[list[str]] = mapped_column(JSONB, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
