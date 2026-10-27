"""Importador dos fluxos consolidados de mercadorias (IBGE, Logística dos Transportes 2024).

Todos os registros entram como flow_class='observed'. As linhas do IBGE são ligações bidirecionais
esquemáticas entre municípios/portos; não representam a rota física percorrida.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.ingestion.common import ValidationReport, import_run, in_brazil, to_wgs84
from app.ingestion.ibge_logistics import UF_BY_CODE
from app.ingestion.sources import ensure_sources
from app.models import Flow

COPY_COLS = (
    "flow_class", "dataset", "source_id", "import_run_id", "modal", "direction",
    "origin_code", "origin_name", "origin_uf", "dest_code", "dest_name", "dest_uf",
    "origin_lon", "origin_lat", "dest_lon", "dest_lat", "product_group", "product",
    "period", "value", "unit", "notes", "attributes", "created_at", "updated_at",
)


@dataclass(frozen=True)
class FlowSpec:
    dataset: str
    rel_path: str
    modal: str
    a_code: str
    a_name: str
    b_code: str
    b_name: str
    value: str
    unit: str
    period: str
    group: str | None = None
    product: str | None = None
    notes: str | None = None
    international: bool = False


BASE = "fluxos_2024"
SPECS = [
    FlowSpec(
        "ibge_2024_rodoviario_ciot", "Fluxos_Rodoviarios/Fluxos rodoviáros/fluxos_rodo_ciots_consol.gpkg",
        "rodoviario", "CD_MUN_A", "ROT_MUN_A", "CD_MUN_B", "ROT_MUN_B", "qtd_ciots",
        "operações (CIOT)", "2023",
        notes="Contagem de Códigos Identificadores de Operação de Transporte; não é tonelagem.",
    ),
    FlowSpec(
        "ibge_2024_ferroviario", "Fluxos_Ferroviarios/Fluxos ferroviários/LIG_FINAL_BID_GEO_TOTAL.gpkg",
        "ferroviario", "CD_MUN_A", "ROT_MUN_A", "CD_MUN_B", "ROT_MUN_B", "Total_TU",
        "TU (tonelada útil)", "não informado",
    ),
    FlowSpec(
        "ibge_2024_aquaviario_cabotagem_interior", "Fluxos_Aquaviarios/Fluxos aquaviários/fluxos_aqua_cabot_interior.gpkg",
        "aquaviario", "CODMUN_A", "ROT_MUN_A", "CODMUN_B", "ROT_MUN_B", "QTD_CARGA",
        "t", "não informado", group="GR_MERC", product="NM_MERC",
        notes="Cabotagem e navegação interior entre instalações portuárias, por mercadoria.",
    ),
    FlowSpec(
        "ibge_2024_aquaviario_internacional", "Fluxos_Aquaviarios/Fluxos aquaviários/fluxos_aqua_inter_bid_consol.gpkg",
        "aquaviario", "CODMUN_A", "ROT_MUN_A", "CODMUN_B", "ROT_MUN_B", "QTD_CARGA",
        "t", "não informado", international=True,
        notes="Longo curso: uma das pontas é país estrangeiro.",
    ),
    FlowSpec(
        "ibge_2024_aereo_domestico", "Fluxos_Aereos/Fluxos aéreos/fluxos_bid_dom_aereo.gpkg",
        "aereo", "COD_CID_A", "ROT_CID_MUN_A", "COD_CID_B", "ROT_CID_MUN_B", "carga_total",
        "kg", "não informado",
    ),
    FlowSpec(
        "ibge_2024_aereo_internacional", "Fluxos_Aereos/Fluxos aéreos/fluxos_bid_inter_aereo.gpkg",
        "aereo", "COD_CID_A", "ROT_MUN_CID_A", "COD_CID_B", "ROT_MUN_CID_B", "carga_total",
        "kg", "não informado", international=True,
    ),
]


def _code(v: Any) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, float):
        return str(int(v))
    return str(v).strip()


def _uf(code: str) -> str | None:
    if code.isdigit() and len(code) == 7:
        return UF_BY_CODE.get(int(code[:2]))
    return None


def _txt(v: Any) -> str:
    """Formata um valor para o protocolo texto do COPY."""
    if v is None:
        return "\\N"
    s = str(v)
    return s.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", " ")


def import_terminals_from_flows(db: Session, raw_dir: Path) -> dict[str, int]:
    """Terminais ferroviários e instalações portuárias identificados nas extremidades das ligações 2024.

    São instalações reais (códigos de terminal ANTT / instalação ANTAQ), mas a posição é a extremidade da
    ligação esquemática do IBGE, que pode coincidir com a sede municipal.
    """
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    from app.ingestion.common import content_hash, upsert_records, validate_point
    from app.models import Facility

    src = ensure_sources(db)["ibge_fluxos_2024"]
    specs = [
        ("terminal_ferroviario", "ferroviario", SPECS[1], ("COD_TF_A", "ROT_TF_A", "CD_MUN_A"), ("COD_TF_B", "ROT_TF_B", "CD_MUN_B"),
         "Terminal ferroviário"),
        ("terminal_portuario", "aquaviario", SPECS[2], ("COD_PORT_A", "NOME_PORTO_A", "CODMUN_A"), ("COD_PORT_B", "NOME_PORTO_B", "CODMUN_B"),
         "Instalação portuária"),
    ]
    out: dict[str, int] = {}
    report = ValidationReport()
    with import_run(db, src, "ibge_2024_terminais", raw_dir / "ibge" / BASE / SPECS[1].rel_path) as run:
        recs: list[dict[str, Any]] = []
        for category, modal, spec, ka, kb, label in specs:
            gdf = to_wgs84(pyogrio.read_dataframe(raw_dir / "ibge" / BASE / spec.rel_path))
            agg: dict[str, dict[str, Any]] = {}
            for row in gdf.itertuples(index=False):
                g = row.geometry
                coords = list(g.coords) if g.geom_type == "LineString" else list(g.geoms[0].coords)
                val = float(getattr(row, spec.value) or 0)
                for keys, xy in ((ka, coords[0]), (kb, coords[-1])):
                    code = _code(getattr(row, keys[0]))
                    if not code:
                        continue
                    item = agg.setdefault(code, {"name": getattr(row, keys[1]), "mun": _code(getattr(row, keys[2])),
                                                 "xy": xy[:2], "total": 0.0, "links": 0})
                    item["total"] += val
                    item["links"] += 1
            for code, it in agg.items():
                run.rows_read += 1
                pt = Point(it["xy"])
                if not validate_point(code, pt, report):
                    continue
                mun = it["mun"]
                rec: dict[str, Any] = {
                    "external_id": f"{category}:2024:{code}", "record_class": "official",
                    "name": f"{label} {it['name']}".strip(), "category": category,
                    "subcategory": "identificado nos fluxos IBGE 2024", "modal": modal,
                    "municipality_code": int(mun) if mun.isdigit() and len(mun) == 7 else None,
                    "uf": _uf(mun), "reliability": "média", "source_reference": "2024",
                    "limitations": (
                        "Localização aproximada (extremidade da ligação esquemática do IBGE). "
                        "Movimentação = soma das ligações bidirecionais incidentes, não capacidade."
                    ),
                    "attributes": {"codigo": code, "movimentacao_ligacoes": round(it["total"], 2),
                                   "unidade_movimentacao": spec.unit, "numero_ligacoes": it["links"]},
                }
                rec["content_hash"] = content_hash(rec, pt)
                rec["geom"] = from_shape(pt, srid=4326)
                recs.append(rec)
            out[category] = len(agg)
        run.rows_rejected = len(report.rejected)
        upsert_records(db, Facility, run, recs)
        run.report = {**run.report, **report.as_dict()}
    return out


def import_flows(db: Session, raw_dir: Path) -> dict[str, int]:
    sources = ensure_sources(db)
    src = sources["ibge_fluxos_2024"]
    counts: dict[str, int] = {}
    for spec in SPECS:
        path = raw_dir / "ibge" / BASE / spec.rel_path
        report = ValidationReport()
        with import_run(db, src, spec.dataset, path) as run:
            gdf: gpd.GeoDataFrame = to_wgs84(pyogrio.read_dataframe(path))
            run.rows_read = len(gdf)
            db.execute(delete(Flow).where(Flow.dataset == spec.dataset, Flow.flow_class == "observed"))
            db.flush()
            now = utcnow().isoformat()
            lines: list[str] = []
            for i, row in enumerate(gdf.itertuples(index=False)):
                geom = row.geometry
                val = getattr(row, spec.value)
                if geom is None or geom.is_empty:
                    report.reject(i, "ligação sem geometria")
                    continue
                if val is None or not np.isfinite(val) or val <= 0:
                    report.reject(i, "valor ausente, não numérico ou não positivo")
                    continue
                coords = list(geom.coords) if geom.geom_type == "LineString" else list(geom.geoms[0].coords)
                (ox, oy), (dx, dy) = coords[0][:2], coords[-1][:2]
                if not spec.international and not (in_brazil(ox, oy) and in_brazil(dx, dy)):
                    report.reject(i, "extremidade fora do Brasil em fluxo doméstico")
                    continue
                a, b = _code(getattr(row, spec.a_code)), _code(getattr(row, spec.b_code))
                if not a or not b:
                    report.reject(i, "código de origem/destino ausente")
                    continue
                vals = [
                    "observed", spec.dataset, src.id, run.id, spec.modal, "bidirectional",
                    a, getattr(row, spec.a_name), _uf(a), b, getattr(row, spec.b_name), _uf(b),
                    ox, oy, dx, dy,
                    getattr(row, spec.group) if spec.group else None,
                    getattr(row, spec.product) if spec.product else None,
                    spec.period, float(val), spec.unit, spec.notes, "{}", now, now,
                ]
                lines.append("\t".join(_txt(v) for v in vals))
            conn = db.connection().connection.driver_connection
            assert conn is not None
            with conn.cursor() as cur:
                with cur.copy(f"COPY flow ({', '.join(COPY_COLS)}) FROM STDIN") as cp:
                    for chunk_start in range(0, len(lines), 20000):
                        cp.write("\n".join(lines[chunk_start:chunk_start + 20000]) + "\n")
            run.rows_inserted = len(lines)
            run.rows_rejected = len(report.rejected)
            run.report = report.as_dict()
            counts[spec.dataset] = len(lines)
    return counts
