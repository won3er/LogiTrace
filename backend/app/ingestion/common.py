"""Utilitários de ingestão: correção de texto, validação, hashing e upsert com proveniência."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shapely.geometry import MultiLineString, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import DataSource, Facility, ImportRun, InfraSegment

if TYPE_CHECKING:
    import geopandas as gpd

log = logging.getLogger("logitrace.ingestion")

# Envelope do território brasileiro (com folga) para rejeitar coordenadas inválidas
BRAZIL_BBOX = (-74.5, -34.5, -28.0, 5.9)


def fix_text(value: Any) -> str | None:
    """Corrige textos de shapefiles com codificação mista (UTF-8 declarado, latin-1 real)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        raw = s.encode("latin-1")
    except UnicodeEncodeError:
        return s
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_hash(payload: dict[str, Any], geom: BaseGeometry | None) -> str:
    body = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    gwkb = geom.wkb_hex if geom is not None else ""
    return hashlib.sha256((body + gwkb).encode()).hexdigest()


def in_brazil(x: float, y: float) -> bool:
    minx, miny, maxx, maxy = BRAZIL_BBOX
    return minx <= x <= maxx and miny <= y <= maxy


def to_wgs84(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    """Garante SRID 4326. SIRGAS 2000 (4674) e WGS84 diferem < 1 m, mas a transformação é explícita."""
    if gdf.crs is None:
        raise ValueError("Camada sem sistema de referência espacial definido (.prj ausente)")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf


def as_multiline(geom: BaseGeometry) -> MultiLineString | None:
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "LineString":
        return MultiLineString([geom])
    if geom.geom_type == "MultiLineString":
        return geom  # type: ignore[return-value]
    if geom.geom_type == "GeometryCollection":
        lines = [g for g in geom.geoms if g.geom_type == "LineString"]
        return MultiLineString(lines) if lines else None
    return None


def as_multipolygon(geom: BaseGeometry) -> MultiPolygon | None:
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = make_valid(geom)
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "MultiPolygon":
        return geom  # type: ignore[return-value]
    if geom.geom_type == "GeometryCollection":
        polys: list[Any] = []
        for g in geom.geoms:
            if g.geom_type == "Polygon":
                polys.append(g)
            elif g.geom_type == "MultiPolygon":
                polys.extend(g.geoms)
        return MultiPolygon(polys) if polys else None
    return None


@dataclass
class ValidationReport:
    rejected: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    duplicates: int = 0

    def reject(self, ref: Any, reason: str) -> None:
        self.rejected.append({"ref": str(ref), "reason": reason})

    def warn(self, ref: Any, reason: str) -> None:
        self.warnings.append({"ref": str(ref), "reason": reason})

    def as_dict(self) -> dict[str, Any]:
        return {
            "rejected": self.rejected[:500],
            "rejected_total": len(self.rejected),
            "warnings": self.warnings[:500],
            "warnings_total": len(self.warnings),
            "duplicates": self.duplicates,
        }


def validate_point(ref: Any, geom: BaseGeometry | None, report: ValidationReport) -> bool:
    if geom is None or geom.is_empty:
        report.reject(ref, "geometria ausente")
        return False
    if geom.geom_type != "Point":
        report.reject(ref, f"geometria {geom.geom_type} onde se esperava Point")
        return False
    if not (math.isfinite(geom.x) and math.isfinite(geom.y)):
        report.reject(ref, "coordenada não finita")
        return False
    if abs(geom.x) < 1e-9 and abs(geom.y) < 1e-9:
        report.reject(ref, "coordenada (0,0)")
        return False
    if not in_brazil(geom.x, geom.y):
        report.reject(ref, f"coordenada fora do território brasileiro ({geom.x:.4f}, {geom.y:.4f})")
        return False
    return True


def validate_line(ref: Any, geom: BaseGeometry | None, report: ValidationReport) -> MultiLineString | None:
    ml = as_multiline(geom) if geom is not None else None
    if ml is None:
        report.reject(ref, "geometria linear ausente ou de tipo inválido")
        return None
    if not ml.is_valid:
        ml = as_multiline(make_valid(ml))
        if ml is None:
            report.reject(ref, "geometria linear inválida e não reparável")
            return None
        report.warn(ref, "geometria reparada com make_valid")
    minx, miny, maxx, maxy = ml.bounds
    if not (in_brazil(minx, miny) and in_brazil(maxx, maxy)):
        report.reject(ref, "segmento fora do envelope do território brasileiro")
        return None
    return ml


@contextmanager
def import_run(db: Session, source: DataSource, dataset: str, file: Path | None) -> Iterator[ImportRun]:
    run = ImportRun(
        source_id=source.id,
        dataset=dataset,
        file_name=str(file.name) if file else None,
        file_sha256=sha256_file(file) if file and file.is_file() else None,
        status="running",
    )
    db.add(run)
    db.flush()
    try:
        yield run
        run.status = "success" if run.rows_rejected == 0 else "partial"
    except Exception:
        # a transação é revertida pelo chamador; a falha fica registrada no log
        log.exception("importação %s falhou", dataset)
        raise
    run.finished_at = utcnow()
    db.flush()
    log.info(
        "import %s: lidos=%s novos=%s alterados=%s inalterados=%s rejeitados=%s",
        dataset, run.rows_read, run.rows_inserted, run.rows_updated, run.rows_unchanged,
        run.rows_rejected,
    )


def upsert_records(
    db: Session,
    model: type[Facility] | type[InfraSegment],
    run: ImportRun,
    records: Iterable[dict[str, Any]],
) -> None:
    """Insere/atualiza por (source_id, external_id) e registra o que mudou desde a última importação."""
    existing = {
        ext: (rid, h)
        for rid, ext, h in db.execute(
            select(model.id, model.external_id, model.content_hash).where(
                model.source_id == run.source_id
            )
        )
    }
    seen: set[str] = set()
    changed: list[str] = []
    for rec in records:
        ext = rec["external_id"]
        if ext in seen:
            run.report.setdefault("duplicated_ids", []).append(ext)
            continue
        seen.add(ext)
        prev = existing.get(ext)
        rec["import_run_id"] = run.id
        rec["source_id"] = run.source_id
        if prev is None:
            db.add(model(**rec))
            run.rows_inserted += 1
        elif prev[1] != rec["content_hash"]:
            obj = db.get(model, prev[0])
            assert obj is not None
            for k, v in rec.items():
                setattr(obj, k, v)
            run.rows_updated += 1
            if len(changed) < 200:
                changed.append(ext)
        else:
            run.rows_unchanged += 1
    missing = sorted(set(existing) - seen)
    run.report = {
        **run.report,
        "changed_ids_sample": changed,
        "missing_from_new_file": missing[:200],
        "missing_total": len(missing),
    }
    db.flush()
