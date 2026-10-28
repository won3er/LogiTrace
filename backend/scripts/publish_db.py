"""Copia os dados do banco local para o banco de produção (ex.: Neon), sem passar por arquivos.

Uso (com as migrações já aplicadas no destino):
    python scripts/publish_db.py <url-postgres-destino>

Copia a base de referência, instalações, segmentos, fluxos e apenas a versão mais recente do grafo.
Cenários, otimizações e tarefas não são copiados (o ambiente publicado começa limpo).
Tabelas de destino são esvaziadas antes da cópia: o comando é idempotente.
"""

from __future__ import annotations

import sys
import time

import psycopg

sys.path.insert(0, ".")
from app.core.config import get_settings  # noqa: E402

TABLES: list[tuple[str, str]] = [
    ("data_source", "TRUE"),
    ("import_run", "TRUE"),
    ("region", "TRUE"),
    ("state", "TRUE"),
    ("municipality", "TRUE"),
    ("assumption", "TRUE"),
    ("facility", "TRUE"),
    ("infra_segment", "TRUE"),
    ("flow", "TRUE"),
    ("network_version", "id = {v}"),
    ("network_node", "version_id = {v}"),
    ("network_edge", "version_id = {v}"),
]
RESET = ["job", "optimization_run", "scenario_run", "scenario_change", "scenario"]


def plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def main(dest_url: str) -> None:
    src = psycopg.connect(plain(get_settings().database_url))
    dst = psycopg.connect(plain(dest_url))
    v = src.execute("SELECT max(id) FROM network_version WHERE status='ready'").fetchone()[0]
    print(f"versão de rede publicada: {v}")
    with dst.transaction():
        dst.execute("TRUNCATE " + ", ".join(RESET + [t for t, _ in reversed(TABLES)]) + " RESTART IDENTITY CASCADE")
        for table, where in TABLES:
            t = time.perf_counter()
            cols = [r[0] for r in dst.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=%s AND table_schema='public' "
                "ORDER BY ordinal_position", (table,))]
            col_sql = ", ".join(cols)
            n = 0
            with src.cursor().copy(f"COPY (SELECT {col_sql} FROM {table} WHERE {where.format(v=v)}) TO STDOUT") as out, \
                    dst.cursor().copy(f"COPY {table} ({col_sql}) FROM STDIN") as inp:
                for chunk in out:
                    inp.write(chunk)
                    n += len(chunk)
            if "id" in cols and table not in ("region", "state", "municipality", "assumption"):
                dst.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce((SELECT max(id) FROM {table}), 1))")
            print(f"  {table}: {n / 1e6:.1f} MB em {time.perf_counter() - t:.1f}s")
        dst.execute("REFRESH MATERIALIZED VIEW mv_municipality_infra")
    dst.execute("ANALYZE")
    size = dst.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
    print(f"concluído; tamanho do banco de destino: {size}")


if __name__ == "__main__":
    main(sys.argv[1])
