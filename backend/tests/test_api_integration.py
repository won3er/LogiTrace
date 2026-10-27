"""Integração: consultas espaciais, rotas na rede construída, importação, cenários, otimização e exportações."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import text

from tests.conftest import wait_job

pytestmark = pytest.mark.usefixtures("test_db")


# ------------------------------------------------------------------ contratos e consultas espaciais
def test_health_and_error_contract(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/facilities/999999")
    assert r.status_code == 404
    assert set(r.json()["error"]) >= {"status", "message"}
    r = client.get("/api/facilities", params={"bbox": "a,b"})
    assert r.status_code == 400


def test_facility_list_contract_and_bbox_filter(client):
    r = client.get("/api/facilities", params={"bbox": "-48,-24,-47,-22"}).json()
    assert set(r) == {"items", "total", "page", "page_size"}
    assert r["total"] == 1 and r["items"][0]["name"] == "Armazém 1"
    item = r["items"][0]
    for k in ("id", "record_class", "category", "lon", "lat", "source_key", "reliability", "limitations", "capacity_value"):
        assert k in item


def test_area_analysis_uses_postgis(client):
    poly = {"type": "Polygon", "coordinates": [[[-48, -24], [-47.3, -24], [-47.3, -22], [-48, -22], [-48, -24]]]}
    r = client.post("/api/territory/area", json={"geometry": poly}).json()
    assert r["municipalities"] == 1 and r["population"] == 100_000
    assert {f["category"]: f["n"] for f in r["facilities"]} == {"armazem": 1}
    road = next(x for x in r["infrastructure_km"] if x["modal"] == "road")
    assert road["km"] > 50  # trechos r1 e r4 dentro do polígono


def test_indicators_have_denominators(client):
    r = client.get("/api/territory/indicators", params={"level": "municipality"}).json()
    rows = {x["code"]: x for x in r["items"]}
    assert rows[3500001]["facilities"] == 1
    assert rows[3500001]["facilities_per_100k"] == pytest.approx(1.0)
    assert r["metrics"]["facilities_per_100k"]["denominator"] == "População 2022"


# ------------------------------------------------------------------ rede
def test_network_route_and_interruption(client):
    body = {"origin": {"type": "municipality", "id": 3500001}, "dest": {"type": "municipality", "id": 3500003},
            "metric": "distance", "alternatives": 2}
    r = client.post("/api/network/route", json=body).json()
    assert r["connected"] and len(r["routes"]) == 2
    best, alt = r["routes"]
    assert best["distance_km"] < alt["distance_km"]
    assert r["straight_km"] < best["distance_km"]  # rede nunca é menor que a linha reta
    seg = client.get("/api/network/nearest", params={"lon": -47.5, "lat": -23.0}).json()
    closed = client.post("/api/network/route", json={**body, "closed_segment_ids": [seg["id"]]}).json()
    assert closed["connected"], "conector secundário deve manter o município acessível"
    detour = closed["routes"][0]
    assert detour["distance_km"] > best["distance_km"]


def test_connectivity_and_bridges(client):
    c = client.get("/api/network/connectivity").json()
    assert c["municipalities_outside_main"] == 0
    b = client.get("/api/network/bridges").json()
    assert isinstance(b["items"], list)


# ------------------------------------------------------------------ importação e validação
def test_user_import_validates_and_detects_duplicates(client):
    csv = "name;lon;lat;capacity_value\nCD Norte;-47.1;-22.5;5000\nCD Norte;-47.1;-22.5;5000\nFora;10;40;1\n;-47;-23;1\n"
    r = client.post("/api/facilities/import", files={"file": ("cds.csv", io.BytesIO(csv.encode()), "text/csv")}).json()
    assert r["created"] == 1 and r["duplicates"] >= 1 and r["rejected_total"] == 2
    lst = client.get("/api/facilities", params={"record_class": "user"}).json()
    assert lst["total"] == 1
    fid = lst["items"][0]["id"]
    official = client.get("/api/facilities", params={"record_class": "official"}).json()["items"][0]["id"]
    assert client.delete(f"/api/facilities/{official}").status_code == 403  # oficiais são somente leitura
    assert client.delete(f"/api/facilities/{fid}").status_code == 204


def test_reimport_detects_changed_records(test_db):
    from app.db.session import session_scope
    from app.ingestion.common import content_hash, import_run, upsert_records
    from app.ingestion.sources import ensure_sources
    from app.models import Facility

    def recs(cap: float) -> list[dict]:
        rec = {"external_id": "porto:t1", "record_class": "official", "name": "Porto T", "category": "porto",
               "modal": "aquaviario", "capacity_value": cap, "attributes": {}, "reliability": "média"}
        rec["content_hash"] = content_hash(rec, None)
        return [rec]

    with session_scope() as db:
        src = ensure_sources(db)["ibge_fluxos_2024"]
        with import_run(db, src, "t1", None) as run:
            upsert_records(db, Facility, run, recs(1.0))
        assert run.rows_inserted == 1
        with import_run(db, src, "t2", None) as run2:
            upsert_records(db, Facility, run2, recs(1.0))
        assert run2.rows_unchanged == 1
        with import_run(db, src, "t3", None) as run3:
            upsert_records(db, Facility, run3, recs(2.0))
        assert run3.rows_updated == 1 and run3.report["changed_ids_sample"] == ["porto:t1"]
        db.execute(text("DELETE FROM facility WHERE external_id='porto:t1'"))


# ------------------------------------------------------------------ cenários e reprodutibilidade
def test_scenario_interruption_and_reproducibility(client):
    seg = client.get("/api/network/nearest", params={"lon": -47.5, "lat": -23.0}).json()
    facs = client.get("/api/facilities", params={"category": "armazem"}).json()["items"]
    sc = client.post("/api/scenarios", json={
        "name": "Teste", "config": {
            "od_benchmark": "none", "metric": "distance", "run_des": True, "des_days": 10,
            "od_pairs": [{"origin": {"type": "municipality", "id": 3500001}, "dest": {"type": "municipality", "id": 3500003}, "volume_t": 100}],
            "service_facility_ids": [f["id"] for f in facs], "demand": {"level": "municipality", "per_capita_t": 0.001},
        },
        "changes": [{"change_type": "closure", "payload": {"segment_ids": [seg["id"]]}},
                    {"change_type": "demand", "payload": {"global_factor": 2.0}}],
    }).json()
    job = wait_job(client, client.post(f"/api/scenarios/{sc['id']}/run").json()["job_id"])
    assert job["status"] == "success", job["error"]
    run = client.get(f"/api/scenarios/runs/{job['ref_id']}").json()
    cmp_ = run["results"]["comparison"]
    assert cmp_["od_pairs_affected"] == 1 and cmp_["od_delta_sum_km"] > 0
    svc = run["results"]["scenario"]["service"]
    # demanda dobrada: 600 mil hab × 0,001 t × 2 = 1.200 t; capacidade = (1000+2000) × 4 giros
    assert svc["kpis"]["total_demand_t"] == pytest.approx(1200)
    for f in svc["open_facilities"]:
        assert f["load_t"] <= f["capacity_t"] + 1e-6
    # reexecução com as mesmas entradas reproduz exatamente o resultado
    job2 = wait_job(client, client.post(f"/api/scenarios/runs/{run['id']}/rerun").json()["job_id"])
    rerun = client.get(f"/api/scenarios/runs/{job2['ref_id']}").json()
    assert rerun["reproduced"] is True and rerun["input_hash"] == run["input_hash"]
    # base não foi alterada
    base = client.post("/api/network/route", json={"origin": {"type": "municipality", "id": 3500001},
                                                   "dest": {"type": "municipality", "id": 3500003}, "metric": "distance"}).json()
    assert base["routes"][0]["distance_km"] == pytest.approx(run["results"]["baseline"]["od"]["pairs"][0]["distance_km"], rel=1e-6)
    # exportações e relatório
    for fmt, ctype in (("xlsx", "spreadsheet"), ("csv", "text/csv"), ("geojson", "geo+json")):
        r = client.get(f"/api/exports/scenario-runs/{run['id']}.{fmt}")
        assert r.status_code == 200 and ctype in r.headers["content-type"]
    pdf = client.get(f"/api/reports/scenario-runs/{run['id']}.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_optimization_via_api_respects_capacity(client):
    body = {"problem": "capacitated_location", "demand": {"level": "municipality", "per_capita_t": 0.01},
            "candidates": {"type": "facilities", "categories": ["armazem"]}, "unmet_penalty_brl_t": 1000, "time_limit_s": 10,
            "metric": "distance"}
    r = client.post("/api/optimization/runs", json=body).json()
    job = wait_job(client, r["job_id"])
    assert job["status"] == "success", job["error"]
    run = client.get(f"/api/optimization/runs/{r['run_id']}").json()
    assert run["quality"] == "OPTIMAL"
    k = run["results"]["kpis"]
    # demanda 6.000 t > capacidade total (1000+2000)×4 = 12.000? não: cabe; verifica balanço
    assert k["served_t"] + k["unmet_t"] == pytest.approx(k["total_demand_t"])
    for f in run["results"]["open_facilities"]:
        assert f["load_t"] <= f["capacity_t"] + 1e-6
    assert client.get(f"/api/reports/optimization-runs/{r['run_id']}.pdf").content[:4] == b"%PDF"


def test_flows_reject_mixed_units(client, test_db):
    from app.db.session import session_scope

    with session_scope() as db:
        for ds, unit in (("a", "t"), ("b", "kg")):
            db.execute(text(
                "INSERT INTO flow (flow_class,dataset,modal,direction,origin_code,origin_name,dest_code,dest_name,origin_lon,origin_lat,"
                "dest_lon,dest_lat,value,unit,attributes,created_at,updated_at) VALUES ('observed',:d,'rodoviario','bidirectional',"
                "'3500001','M1','3500003','M3',-47.6,-23,-46.3,-23,10,:u,'{}',now(),now())"), {"d": ds, "u": unit})
    assert client.get("/api/flows", params={"dataset": ["a", "b"]}).status_code == 400
    ok = client.get("/api/flows", params={"dataset": ["a"]}).json()
    assert ok["unit"] == "t" and "esquemática" in ok["caveat"]


def test_tiles_are_mvt(client):
    r = client.get("/api/tiles/segments/8/94/145.pbf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/vnd.mapbox-vector-tile"
