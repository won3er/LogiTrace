"""Linha de comando do LogiTrace.

Uso:
    python -m app.cli download            # baixa as bases públicas para data/raw
    python -m app.cli ingest              # importa território, instalações, segmentos e fluxos
    python -m app.cli build-network       # constrói uma nova versão do grafo multimodal
    python -m app.cli refresh-stats       # recalcula agregações territoriais pré-calculadas
    python -m app.cli setup               # download + ingest + build-network
    python -m app.cli deploy-init         # extensões + migrações; dispara o setup em segundo plano se o banco estiver vazio
"""

from __future__ import annotations

import argparse
import logging
import time

from app.core.assumptions import seed_assumptions
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.ingestion.download import download_all
from app.ingestion.ibge_flows import import_flows, import_terminals_from_flows
from app.ingestion.ibge_logistics import import_facilities, import_segments
from app.ingestion.ibge_territory import import_territory
from app.ingestion.sources import ensure_sources

log = logging.getLogger("logitrace.cli")


def cmd_ingest(steps: list[str]) -> None:
    raw = get_settings().raw_dir
    with session_scope() as db:
        ensure_sources(db)
        seed_assumptions(db)
    actions = {
        "territory": import_territory,
        "facilities": import_facilities,
        "terminals": import_terminals_from_flows,
        "segments": import_segments,
        "flows": import_flows,
    }
    for step in steps:
        t = time.perf_counter()
        with session_scope() as db:
            res = actions[step](db, raw)
        log.info("%s concluído em %.1fs: %s", step, time.perf_counter() - t, res)


def cmd_refresh_stats() -> None:
    from sqlalchemy import text

    with session_scope() as db:
        db.execute(text("REFRESH MATERIALIZED VIEW mv_municipality_infra"))
    log.info("estatísticas territoriais atualizadas")


def cmd_build_network() -> None:
    from app.network.builder import build_network

    with session_scope() as db:
        v = build_network(db)
        log.info("versão %s: %s", v.id, v.stats)


def cmd_deploy_init() -> None:
    """Prepara o banco na nuvem: PostGIS, migrações e, se não houver dados, o setup completo em segundo plano."""
    import subprocess
    import sys

    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from app.core.config import BACKEND_DIR
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    with session_scope() as db:
        has_data = db.execute(text("SELECT EXISTS (SELECT 1 FROM network_version)")).scalar()
    if has_data:
        log.info("banco já populado; setup ignorado")
        return
    log.info("banco vazio: iniciando setup em segundo plano")
    subprocess.Popen([sys.executable, "-m", "app.cli", "setup"], start_new_session=True)


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser(prog="logitrace")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--force", action="store_true")
    i = sub.add_parser("ingest")
    i.add_argument("--only", nargs="*", default=["territory", "facilities", "terminals", "segments", "flows"])
    sub.add_parser("build-network")
    sub.add_parser("refresh-stats")
    sub.add_parser("setup")
    sub.add_parser("deploy-init")
    args = p.parse_args()
    if args.cmd == "download":
        log.info("baixados: %s", download_all(get_settings().raw_dir, force=args.force))
    elif args.cmd == "ingest":
        cmd_ingest(args.only)
        cmd_refresh_stats()
    elif args.cmd == "build-network":
        cmd_build_network()
    elif args.cmd == "refresh-stats":
        cmd_refresh_stats()
    elif args.cmd == "setup":
        download_all(get_settings().raw_dir)
        cmd_ingest(["territory", "facilities", "terminals", "segments", "flows"])
        cmd_refresh_stats()
        cmd_build_network()
    elif args.cmd == "deploy-init":
        cmd_deploy_init()


if __name__ == "__main__":
    main()
