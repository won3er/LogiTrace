"""Fixtures de integração: banco de teste PostGIS recriado por migrações e um recorte territorial sintético.

O recorte é pequeno e controlado (3 municípios, 6 trechos rodoviários, 2 armazéns) para que distâncias e
alocações possam ser conferidas à mão. Os testes unitários (grafo e solvers) não usam banco.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, box
from sqlalchemy import text

from app.core.config import get_settings

INTEGRATION = os.environ.get("LOGITRACE_SKIP_DB") != "1"


@pytest.fixture(scope="session")
def test_db() -> Iterator[None]:
    if not INTEGRATION:
        pytest.skip("LOGITRACE_SKIP_DB=1")
    from alembic import command
    from alembic.config import Config

    from app.db.session import configure_engine
    from app.network.engine import clear_cache

    url = get_settings().test_database_url
    os.environ["LOGITRACE_ALEMBIC_URL"] = url
    cfg = Config(str(get_settings().data_dir.parent / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(get_settings().data_dir.parent / "backend" / "alembic"))
    engine = configure_engine(url)
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    clear_cache()
    _seed()
    yield
    clear_cache()


def _seed() -> None:
    from app.core.assumptions import seed_assumptions
    from app.db.session import session_scope
    from app.ingestion.sources import ensure_sources
    from app.models import Facility, ImportRun, InfraSegment, Municipality, Region, State
    from app.network.builder import build_network

    with session_scope() as db:
        src = ensure_sources(db)["ibge_logistica_2014"]
        seed_assumptions(db)
        run = ImportRun(source_id=src.id, dataset="fixture", status="success")
        db.add(run)
        db.add(Region(code=3, abbrev="SE", name="Sudeste"))
        db.flush()
        db.add(State(code=35, uf="SP", name="São Paulo", region_code=3,
                     geom=from_shape(MultiPolygon([box(-48, -24, -46, -22)]), srid=4326)))
        db.flush()
        for i, (x0, x1, pop) in enumerate([(-48, -47.3, 100_000), (-47.3, -46.6, 200_000), (-46.6, -46, 300_000)]):
            db.add(Municipality(code=3500001 + i, name=f"Município {i + 1}", uf="SP", state_code=35, region_code=3,
                                immediate_region_code=350001 + i, immediate_region_name=f"RGI {i + 1}",
                                intermediate_region_code=3501, intermediate_region_name="RGInt",
                                population=pop, population_year=2022, gdp_thousand_brl=pop * 50.0, gdp_year=2021,
                                geom=from_shape(MultiPolygon([box(x0, -24, x1, -22)]), srid=4326)))
        lines = {
            "r1": [(-47.9, -23.0), (-47.0, -23.0)],
            "r2": [(-47.0, -23.0), (-46.1, -23.0)],
            "r3": [(-47.0, -23.0), (-47.0, -22.2)],
            "r4": [(-47.9, -23.0), (-47.65, -23.1)],
            "r4b": [(-47.65, -23.1), (-47.0, -23.6)],
            "r5": [(-47.0, -23.6), (-46.1, -23.0)],
        }
        for i, (k, pts) in enumerate(lines.items()):
            db.add(InfraSegment(external_id=f"fixture:{k}", source_id=src.id, import_run_id=run.id, record_class="official",
                                modal="road", code=f"00{i + 1}BSP0010", name=k, jurisdiction="federal", surface="Pavimentada",
                                uf="SP", length_km=0, attributes={}, content_hash=k,
                                geom=from_shape(MultiLineString([LineString(pts)]), srid=4326)))
        for i, (x, y, cap) in enumerate([(-47.8, -23.05, 1000.0), (-46.2, -22.95, 2000.0)]):
            db.add(Facility(external_id=f"armazem:fixture{i}", source_id=src.id, import_run_id=run.id, record_class="official",
                            name=f"Armazém {i + 1}", category="armazem", modal="rodoviario", capacity_value=cap,
                            capacity_unit="t (estática)", municipality_code=3500001 + 2 * i, uf="SP", reliability="média",
                            attributes={}, content_hash=f"f{i}", geom=from_shape(Point(x, y), srid=4326)))
        db.flush()
        db.execute(text("UPDATE infra_segment SET length_km = ST_Length(geom::geography)/1000"))
        db.execute(text("UPDATE municipality SET area_km2 = ST_Area(geom::geography)/1e6, centroid = ST_PointOnSurface(geom)"))
        db.execute(text("UPDATE state SET area_km2 = ST_Area(geom::geography)/1e6"))
    with session_scope() as db:
        db.execute(text("REFRESH MATERIALIZED VIEW mv_municipality_infra"))
        build_network(db, label="fixture")


@pytest.fixture(scope="session")
def client(test_db):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def wait_job(client, job_id: int, timeout: float = 60.0) -> dict:  # type: ignore[no-untyped-def]
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("success", "failed"):
            return j
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} não terminou")
