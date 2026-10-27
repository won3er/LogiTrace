"""Importador da base 'Logística dos Transportes no Brasil 2014' (IBGE)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from geoalchemy2.shape import from_shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.common import (
    ValidationReport,
    content_hash,
    fix_text,
    import_run,
    to_wgs84,
    upsert_records,
    validate_line,
    validate_point,
)
from app.ingestion.sources import ensure_sources
from app.models import DataSource, Facility, InfraSegment, Municipality

UF_BY_CODE = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI",
    23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES",
    33: "RJ", 35: "SP", 41: "PR", 42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}
JURISDICTION = {
    "B": "federal", "E": "estadual", "L": "estadual (ligação)", "D": "distrital",
    "A": "acesso", "C": "coincidente",
}
URBAN_PASSENGER_RAIL = ("Trens Urbanos", "Trens Metropolitanos", "Metr")


def _read(path: Path) -> gpd.GeoDataFrame:
    gdf = pyogrio.read_dataframe(path, encoding="latin1")
    return to_wgs84(gdf)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def _mun_code(v: Any) -> int | None:
    f = _num(v)
    if f is None:
        return None
    code = int(f)
    return code if 1_000_000 <= code <= 5_399_999 else None


class _MunicipalityIndex:
    def __init__(self, db: Session) -> None:
        self.by_code = {
            c: (n, uf) for c, n, uf in db.execute(select(Municipality.code, Municipality.name, Municipality.uf))
        }

    def resolve(self, code: int | None) -> tuple[int | None, str | None, str | None]:
        if code is None:
            return None, None, None
        hit = self.by_code.get(code)
        if hit is None:
            return None, None, None
        return code, hit[0], hit[1]


def _facility_records(
    gdf: gpd.GeoDataFrame,
    report: ValidationReport,
    mun: _MunicipalityIndex,
    build: Callable[[pd.Series], dict[str, Any]],
    *,
    id_col: str,
) -> Iterator[dict[str, Any]]:
    for _, row in gdf.iterrows():
        ref = row[id_col]
        geom: BaseGeometry = row.geometry
        if not validate_point(ref, geom, report):
            continue
        rec = build(row)
        code, mname, muf = mun.resolve(rec.pop("_mun_code", None))
        if code is None:
            report.warn(ref, "código de município ausente ou inexistente na base IBGE atual")
        rec.setdefault("municipality_code", code)
        rec.setdefault("municipality_name", mname or rec.pop("_mun_name", None))
        rec.setdefault("uf", muf or rec.pop("_uf", None))
        rec.pop("_mun_name", None)
        rec.pop("_uf", None)
        rec["external_id"] = f"{rec['category']}:{int(ref)}"
        rec["record_class"] = "official"
        payload = {k: v for k, v in rec.items() if k != "external_id"}
        rec["content_hash"] = content_hash(payload, geom)
        rec["geom"] = from_shape(geom, srid=4326)
        yield rec


def _airport_names(raw_dir: Path) -> gpd.GeoDataFrame | None:
    """Nomes e códigos ICAO via OurAirports (domínio público), associados por proximidade (< 5 km)."""
    p = raw_dir / "ourairports" / "airports.csv"
    if not p.is_file():
        return None
    df = pd.read_csv(p, usecols=["ident", "type", "name", "iso_country", "gps_code", "iata_code", "latitude_deg", "longitude_deg"])
    df = df[(df.iso_country == "BR") & df.type.isin(["large_airport", "medium_airport", "small_airport"])]
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude_deg, df.latitude_deg), crs=4326).to_crs(5880)


def import_facilities(db: Session, raw_dir: Path) -> dict[str, int]:
    sources = ensure_sources(db)
    src: DataSource = sources["ibge_logistica_2014"]
    base = raw_dir / "ibge" / "base_2014" / "2014"
    mun = _MunicipalityIndex(db)
    report = ValidationReport()
    counts: dict[str, int] = {}
    lim_name = "Nome derivado do município: a base IBGE 2014 não traz o nome oficial da instalação."

    def portos(r: pd.Series) -> dict[str, Any]:
        city = fix_text(r.MUNICIPIO)
        return {
            "name": f"Porto de {city}", "category": "porto", "subcategory": "porto público",
            "modal": "aquaviario", "_mun_code": _mun_code(r.codmun), "_uf": UF_BY_CODE.get(int(r.UF)),
            "status": "em operação (2014)", "reliability": "média",
            "limitations": lim_name + " Movimentação total refere-se ao ano-base da publicação IBGE 2014.",
            "source_reference": "2014",
            "attributes": {"movimentacao_total_t": _num(r.Sum_TOTAL), "regiao": fix_text(r.NOME_REGIA)},
        }

    def terminais(r: pd.Series) -> dict[str, Any]:
        return {
            "name": f"Terminal portuário {fix_text(r.NOME)}", "category": "terminal_portuario",
            "subcategory": "outros terminais portuários", "modal": "aquaviario",
            "_mun_code": _mun_code(r.GEOCODIG_M), "_mun_name": fix_text(r.NOME_MUNIC), "_uf": fix_text(r.UF),
            "status": None, "reliability": "média",
            "limitations": "Sem operador, capacidade ou movimentação na fonte.", "source_reference": "2014",
            "attributes": {},
        }

    def portos_secos(r: pd.Series) -> dict[str, Any]:
        return {
            "name": f"Porto seco {fix_text(r.ADM)}", "category": "porto_seco",
            "subcategory": "recinto alfandegado", "modal": "intermodal",
            "_mun_code": _mun_code(r.GEOCODIGO), "_mun_name": fix_text(r.NOME_MUNI),
            "reliability": "média", "limitations": "Sem capacidade ou operador na fonte.",
            "source_reference": "2014", "attributes": {"administracao": fix_text(r.ADM)},
        }

    def armazens(r: pd.Series) -> dict[str, Any]:
        cap = _num(r.CAP_TON)
        city = fix_text(r.MUNICIPIO)
        return {
            "name": f"Armazenagem agregada — {city.title() if city else '?'}", "category": "armazem",
            "subcategory": "capacidade estática municipal", "modal": "rodoviario",
            "_mun_code": _mun_code(r.GEOCODIGO), "_uf": fix_text(r.UF),
            "capacity_value": cap if cap and cap > 0 else None, "capacity_unit": "t (estática)" if cap and cap > 0 else None,
            "reliability": "média",
            "limitations": (
                "Registro agregado por município (um ponto por município, na posição da sede). "
                "Não identifica armazéns individuais, operador ou situação operacional."
            ),
            "source_reference": "2014", "attributes": {},
        }

    def pontos_fronteira(r: pd.Series) -> dict[str, Any]:
        return {
            "name": f"Ponto de fronteira — {fix_text(r.MUNICIPIO)}", "category": "ponto_fronteira",
            "subcategory": "passagem de fronteira", "modal": "rodoviario",
            "_mun_code": _mun_code(r.MUNICDV), "operator": fix_text(r.Administra),
            "reliability": "média", "limitations": lim_name, "source_reference": "2014",
            "attributes": {},
        }

    def aerodromos(r: pd.Series) -> dict[str, Any]:
        return {
            "name": f"Aeródromo {fix_text(r.NOME)}", "category": "aerodromo",
            "subcategory": fix_text(r.TIPOAERO), "modal": "aereo",
            "_mun_code": _mun_code(r.GEOCODIGO), "_mun_name": fix_text(r.NM_MUNICIP), "_uf": fix_text(r.UF),
            "reliability": "média", "limitations": "Sem dados de carga.", "source_reference": "2014",
            "attributes": {"icao": fix_text(r.COD_ICAO), "uso": fix_text(r.COD_USO)},
        }

    layers: list[tuple[str, Callable[[pd.Series], dict[str, Any]], str]] = [
        ("portos_2014", portos, "OBJECTID_1"),
        ("outros_term_portuarios_2014", terminais, "OBJECTID"),
        ("porto_seco_2014", portos_secos, "OBJECTID"),
        ("armazens_2014", armazens, "OBJECTID"),
        ("pontos_fronteira_2014", pontos_fronteira, "OBJECTID_1"),
        ("outros_aerodromos_2014", aerodromos, "OBJECTID"),
    ]
    with import_run(db, src, "ibge_2014_instalacoes", base / "portos_2014.shp") as run:
        all_recs: list[dict[str, Any]] = []
        for layer, fn, idc in layers:
            gdf = _read(base / f"{layer}.shp")
            run.rows_read += len(gdf)
            recs = list(_facility_records(gdf, report, mun, fn, id_col=idc))
            counts[layer] = len(recs)
            all_recs.extend(recs)

        # Aeroportos com movimento de passageiros (2010) + carga (2010) + nome via OurAirports
        aero = _read(base / "aeroportos_2014.shp")
        carga = _read(base / "mov_carga_aero_2010.shp")
        carga_by_mun = {int(_num(c.GEOCODIGO) or 0): (_num(c.CARGA__KG_), fix_text(c.NOME)) for _, c in carga.iterrows()}
        names = _airport_names(raw_dir)
        aero_m = aero.to_crs(5880)
        run.rows_read += len(aero)

        def aeroportos(r: pd.Series) -> dict[str, Any]:
            code = _mun_code(r.MUNICDV)
            attrs: dict[str, Any] = {"passageiros_2010": _num(r.PAX2010), "passageiros_internacionais_2010": _num(r.Internacio)}
            if code and code in carga_by_mun:
                attrs["carga_kg_2010"] = carga_by_mun[code][0]
            name = f"Aeroporto de {fix_text(r.MUNICIPIO)}"
            lim = "Movimentos referentes a 2010."
            if names is not None:
                pt = aero_m.geometry.loc[r.name]
                d = names.distance(pt)
                i = d.idxmin()
                if d.loc[i] < 5000:
                    hit = names.loc[i]
                    name = str(hit["name"])
                    attrs.update({"icao": hit["gps_code"] if isinstance(hit["gps_code"], str) else None,
                                  "iata": hit["iata_code"] if isinstance(hit["iata_code"], str) else None,
                                  "nome_fonte": "OurAirports (domínio público), associação espacial < 5 km",
                                  "distancia_associacao_m": round(float(d.loc[i]), 1)})
                else:
                    lim = lim_name + " " + lim
            return {
                "name": name, "category": "aeroporto", "subcategory": "aeroporto com movimento regular",
                "modal": "aereo", "_mun_code": code, "_uf": UF_BY_CODE.get(int(r.UF)),
                "reliability": "média", "limitations": lim, "source_reference": "2010/2014",
                "attributes": attrs,
            }

        recs = list(_facility_records(aero, report, mun, aeroportos, id_col="OBJECTID_1"))
        counts["aeroportos_2014"] = len(recs)
        all_recs.extend(recs)
        run.rows_rejected = len(report.rejected)
        upsert_records(db, Facility, run, all_recs)
        run.report = {**run.report, **report.as_dict(), "per_layer": counts}
    return counts


def import_segments(db: Session, raw_dir: Path) -> dict[str, int]:
    sources = ensure_sources(db)
    src = sources["ibge_logistica_2014"]
    base = raw_dir / "ibge" / "base_2014" / "2014"
    counts: dict[str, int] = {}

    def lengths_km(gdf: gpd.GeoDataFrame) -> pd.Series:
        # comprimento geodésico aproximado em projeção cônica de área/distância para o Brasil (SIRGAS 2000 / Brazil Polyconic)
        return gdf.to_crs(5880).length / 1000.0

    specs: list[tuple[str, str, str, Callable[[pd.Series], dict[str, Any]]]] = [
        ("rodovia_2014", "road", "OBJECTID", lambda r: {
            "code": fix_text(r.CODIGO), "name": fix_text(r.DescSeg),
            "jurisdiction": JURISDICTION.get(str(r.CODIGO)[3:4], "não classificada") if isinstance(r.CODIGO, str) else None,
            "surface": fix_text(r.TipoPNV), "situation": fix_text(r.TipoPNV),
            "uf": str(r.CODIGO)[4:6] if isinstance(r.CODIGO, str) and str(r.CODIGO)[3:4] in "BELDAC" else None,
            "attributes": {},
        }),
        ("ferrovias_2014", "rail", "OBJECTID", lambda r: {
            "code": fix_text(r.COD_PNV), "name": fix_text(r.FERROVIA), "jurisdiction": "federal",
            "surface": None, "situation": None, "uf": str(r.COD_PNV)[4:6] if isinstance(r.COD_PNV, str) else None,
            "attributes": {
                "operadora": fix_text(r.OPERADORA), "codigo_simplificado": fix_text(r.CODPNVSIMP),
                "urbano_passageiros": any(k in (fix_text(r.OPERADORA) or "") for k in URBAN_PASSENGER_RAIL),
            },
        }),
        ("hidrovias_linha_2014", "waterway", "OBJECTID_1", lambda r: {
            "code": None, "name": "Via navegável", "jurisdiction": "federal", "surface": None,
            "situation": None, "uf": None, "attributes": {},
        }),
        ("eixo_rodoviario_estruturante_2014", "road_axis", "OBJECTID", lambda r: {
            "code": fix_text(r.CODIGO), "name": fix_text(r.DescSeg), "jurisdiction": None,
            "surface": fix_text(r.TipoPNV), "situation": fix_text(r.TipoPNV), "uf": None,
            "attributes": {"eixo_estruturante": True},
        }),
    ]
    for layer, modal, idc, build in specs:
        report = ValidationReport()
        path = base / f"{layer}.shp"
        with import_run(db, src, f"ibge_2014_{layer}", path) as run:
            gdf = _read(path)
            gdf["_len"] = lengths_km(gdf)
            run.rows_read = len(gdf)
            recs: list[dict[str, Any]] = []
            for _, row in gdf.iterrows():
                ref = row[idc]
                ml = validate_line(ref, row.geometry, report)
                if ml is None:
                    continue
                if row["_len"] <= 0:
                    report.reject(ref, "comprimento nulo")
                    continue
                rec = build(row)
                rec.update(
                    external_id=f"{layer}:{int(ref)}", modal=modal, record_class="official",
                    length_km=float(row["_len"]),
                )
                rec["content_hash"] = content_hash({k: v for k, v in rec.items() if k != "external_id"}, ml)
                rec["geom"] = from_shape(ml, srid=4326)
                recs.append(rec)
            run.rows_rejected = len(report.rejected)
            upsert_records(db, InfraSegment, run, recs)
            run.report = {**run.report, **report.as_dict()}
            counts[layer] = len(recs)
    return counts
