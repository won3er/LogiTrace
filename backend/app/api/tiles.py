"""Tiles vetoriais (MVT) gerados pelo PostGIS, com seleção de feições por nível de zoom.

Evita enviar a malha nacional inteira ao navegador: cada tile contém só as feições que o cruzam,
quantizadas e recortadas por ST_AsMVTGeom.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from app.api.common import DB

router = APIRouter(prefix="/tiles", tags=["tiles"])

Layer = Literal["segments", "municipalities", "states", "corridors", "network"]
_cache: OrderedDict[str, bytes] = OrderedDict()
_lock = Lock()
CACHE_MAX = 4000


def _segments_filter(z: int) -> str:
    if z < 5:
        return "s.modal IN ('rail','waterway') OR (s.modal='road' AND s.jurisdiction='federal' AND s.surface IN ('Duplicada','Pavimentada'))"
    if z < 7:
        return "s.modal IN ('rail','waterway') OR (s.modal='road' AND (s.jurisdiction='federal' OR s.surface='Duplicada'))"
    return "s.modal IN ('road','rail','waterway')"


SQL: dict[str, str] = {
    "segments": """
        SELECT ST_AsMVT(t, 'segments', 4096, 'geom', 'id') FROM (
          SELECT s.id, s.modal, s.code, s.name, s.surface, s.jurisdiction, round(s.length_km::numeric,2) AS km,
                 ST_AsMVTGeom(ST_Transform(s.geom, 3857), ST_TileEnvelope(:z,:x,:y), 4096, 64, true) AS geom
          FROM infra_segment s
          WHERE s.geom && ST_Transform(ST_TileEnvelope(:z,:x,:y), 4326) AND ({filter})
            AND coalesce(s.surface,'') NOT IN ('Planejada')
        ) t""",
    "corridors": """
        SELECT ST_AsMVT(t, 'corridors', 4096, 'geom', 'id') FROM (
          SELECT s.id, s.code, s.name, s.surface,
                 ST_AsMVTGeom(ST_Transform(s.geom, 3857), ST_TileEnvelope(:z,:x,:y), 4096, 64, true) AS geom
          FROM infra_segment s WHERE s.modal='road_axis' AND s.geom && ST_Transform(ST_TileEnvelope(:z,:x,:y), 4326)
        ) t""",
    "municipalities": """
        SELECT ST_AsMVT(t, 'municipalities', 4096, 'geom', 'code') FROM (
          SELECT m.code, m.name, m.uf, m.population,
                 ST_AsMVTGeom(ST_Transform(ST_SimplifyPreserveTopology(m.geom, {tol}), 3857), ST_TileEnvelope(:z,:x,:y), 4096, 16, true) AS geom
          FROM municipality m WHERE m.geom && ST_Transform(ST_TileEnvelope(:z,:x,:y), 4326)
        ) t""",
    "states": """
        SELECT ST_AsMVT(t, 'states', 4096, 'geom', 'code') FROM (
          SELECT s.code, s.uf, s.name,
                 ST_AsMVTGeom(ST_Transform(ST_SimplifyPreserveTopology(s.geom, {tol}), 3857), ST_TileEnvelope(:z,:x,:y), 4096, 16, true) AS geom
          FROM state s WHERE s.geom && ST_Transform(ST_TileEnvelope(:z,:x,:y), 4326)
        ) t""",
    "network": """
        SELECT ST_AsMVT(t, 'network', 4096, 'geom', 'edge_idx') FROM (
          SELECT e.edge_idx, e.modal, e.code, round(e.length_km::numeric,2) km, round(e.time_h::numeric,3) time_h,
                 round(e.cost_brl_t::numeric,2) cost,
                 ST_AsMVTGeom(ST_Transform(e.geom, 3857), ST_TileEnvelope(:z,:x,:y), 4096, 64, true) AS geom
          FROM network_edge e
          WHERE e.version_id = (SELECT max(id) FROM network_version WHERE status='ready')
            AND e.geom && ST_Transform(ST_TileEnvelope(:z,:x,:y), 4326) {netfilter}
        ) t""",
}


# Em zooms baixos os trechos são agregados por modal/jurisdição e simplificados (poucas feições por tile)
SEGMENTS_LOW_ZOOM = """
    SELECT ST_AsMVT(t, 'segments', 4096, 'geom') FROM (
      SELECT s.modal, s.jurisdiction,
             CASE WHEN s.surface IN ('Duplicada','Pavimentada') THEN s.surface ELSE 'outra' END AS surface,
             ST_AsMVTGeom(ST_Transform(ST_Simplify(ST_Collect(s.geom), {tol}), 3857), ST_TileEnvelope(:z,:x,:y), 4096, 64, true) AS geom
      FROM infra_segment s
      WHERE s.geom && ST_Transform(ST_TileEnvelope(:z,:x,:y), 4326) AND ({filter})
      GROUP BY 1, 2, 3
    ) t WHERE geom IS NOT NULL"""


@router.get("/{layer}/{z}/{x}/{y}.pbf")
def tile(db: DB, layer: Layer, z: int, x: int, y: int) -> Response:
    if not (0 <= z <= 16 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(400, "Tile inválido")
    if layer == "municipalities" and z < 4:
        return Response(b"", media_type="application/vnd.mapbox-vector-tile")
    key = f"{layer}/{z}/{x}/{y}"
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
    if hit is None:
        tol = max(0.0005, 0.08 / (2 ** max(z - 3, 0)))
        tpl = SEGMENTS_LOW_ZOOM if layer == "segments" and z < 6 else SQL[layer]
        sql = tpl.format(filter=_segments_filter(z), tol=tol,
                                netfilter="" if z >= 8 else "AND e.modal IN ('road','rail','waterway','transfer')")
        hit = db.execute(text(sql), {"z": z, "x": x, "y": y}).scalar() or b""
        with _lock:
            _cache[key] = hit
            if len(_cache) > CACHE_MAX:
                _cache.popitem(last=False)
    return Response(content=bytes(hit), media_type="application/vnd.mapbox-vector-tile",
                    headers={"Cache-Control": "public, max-age=3600"})


def clear_tile_cache() -> None:
    with _lock:
        _cache.clear()
