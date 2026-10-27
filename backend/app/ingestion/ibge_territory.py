"""Importador da base territorial do IBGE: regiões, UFs e municípios com população e PIB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
from geoalchemy2.shape import from_shape
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.ingestion.common import ValidationReport, as_multipolygon, import_run, to_wgs84
from app.ingestion.sources import ensure_sources
from app.models import Municipality, Region, State

REGIONS = {1: ("N", "Norte"), 2: ("NE", "Nordeste"), 3: ("SE", "Sudeste"), 4: ("S", "Sul"), 5: ("CO", "Centro-Oeste")}


def _sidra_values(path: Path) -> tuple[dict[int, float], int | None]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, float] = {}
    year: int | None = None
    for r in rows[1:]:
        v = r.get("V")
        if v in (None, "", "-", "...", "X"):
            continue
        out[int(r["D1C"])] = float(v)
        year = int(r["D3C"])
    return out, year


def import_territory(db: Session, raw_dir: Path) -> dict[str, Any]:
    sources = ensure_sources(db)
    ibge = raw_dir / "ibge"
    report = ValidationReport()

    municipios: list[dict[str, Any]] = json.loads((ibge / "municipios.json").read_text(encoding="utf-8"))
    pop, pop_year = _sidra_values(ibge / "pop_censo2022.json")
    gdp, gdp_year = _sidra_values(ibge / "pib_municipal.json")

    with import_run(db, sources["ibge_malhas"], "ibge_ufs", ibge / "malha_ufs.geojson") as run:
        ufs = to_wgs84(gpd.read_file(ibge / "malha_ufs.geojson"))
        db.execute(delete(Municipality))
        db.execute(delete(State))
        db.execute(delete(Region))
        for code, (abbrev, name) in REGIONS.items():
            db.add(Region(code=code, abbrev=abbrev, name=name))
        db.flush()
        uf_meta: dict[int, dict[str, Any]] = {}
        for m in municipios:
            uf = m["microrregiao"]["mesorregiao"]["UF"] if m.get("microrregiao") else m["regiao-imediata"]["regiao-intermediaria"]["UF"]
            uf_meta[uf["id"]] = uf
        for _, row in ufs.iterrows():
            run.rows_read += 1
            code = int(row["codarea"])
            meta = uf_meta.get(code)
            geom = as_multipolygon(row.geometry)
            if meta is None or geom is None:
                report.reject(code, "UF sem metadados ou geometria")
                run.rows_rejected += 1
                continue
            db.add(
                State(
                    code=code, uf=meta["sigla"], name=meta["nome"], region_code=meta["regiao"]["id"],
                    geom=from_shape(geom, srid=4326), import_run_id=run.id,
                )
            )
            run.rows_inserted += 1
        db.flush()
        db.execute(text("UPDATE state SET area_km2 = ST_Area(geom::geography)/1e6"))
        run.report = report.as_dict()

    report = ValidationReport()
    with import_run(db, sources["ibge_localidades"], "ibge_municipios", ibge / "malha_municipios.geojson") as run:
        mun = to_wgs84(gpd.read_file(ibge / "malha_municipios.geojson"))
        geoms = {int(r["codarea"]): r.geometry for _, r in mun.iterrows()}
        for m in municipios:
            run.rows_read += 1
            code = int(m["id"])
            ri = m.get("regiao-imediata") or {}
            rint = ri.get("regiao-intermediaria") or {}
            uf = rint.get("UF") or m["microrregiao"]["mesorregiao"]["UF"]
            geom = as_multipolygon(geoms.get(code))  # type: ignore[arg-type]
            if geom is None:
                report.reject(code, "município sem geometria na malha")
                run.rows_rejected += 1
                continue
            if code not in pop:
                report.warn(code, "sem população no Censo 2022")
            db.add(
                Municipality(
                    code=code, name=m["nome"], uf=uf["sigla"], state_code=uf["id"],
                    region_code=uf["regiao"]["id"],
                    immediate_region_code=ri.get("id"), immediate_region_name=ri.get("nome"),
                    intermediate_region_code=rint.get("id"), intermediate_region_name=rint.get("nome"),
                    population=int(pop[code]) if code in pop else None,
                    population_year=pop_year,
                    gdp_thousand_brl=gdp.get(code), gdp_year=gdp_year if code in gdp else None,
                    geom=from_shape(geom, srid=4326), import_run_id=run.id,
                )
            )
            run.rows_inserted += 1
        db.flush()
        db.execute(
            text(
                "UPDATE municipality SET area_km2 = ST_Area(geom::geography)/1e6, "
                "centroid = ST_PointOnSurface(geom)"
            )
        )
        run.report = report.as_dict()
    return {"states": len(ufs), "municipalities": len(municipios)}
