"""Execução assíncrona de tarefas pesadas (otimizações, cenários, criticidade, reconstrução da rede).

Usa um pool de threads do próprio processo e a tabela `job` para acompanhamento. Não exige Redis:
para um único servidor de API isso é suficiente; o contrato (POST -> job_id, GET /jobs/{id}) permite
trocar por uma fila externa no futuro sem mudar o frontend.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models import Job

log = logging.getLogger("logitrace.jobs")
_executor: ThreadPoolExecutor | None = None


def executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=get_settings().job_workers, thread_name_prefix="job")
    return _executor


class JobContext:
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id

    def progress(self, value: float, message: str | None = None) -> None:
        with SessionLocal() as db:
            job = db.get(Job, self.job_id)
            if job:
                job.progress = max(0.0, min(1.0, value))
                if message:
                    job.message = message
                db.commit()


def submit(
    kind: str, fn: Callable[[JobContext], tuple[str, int] | None], params: dict[str, Any] | None = None,
    *, ref_type: str | None = None, ref_id: int | None = None, sync: bool = False,
) -> int:
    """Enfileira `fn(ctx)`; a função pode retornar (ref_type, ref_id) do objeto produzido."""
    with SessionLocal() as db:
        job = Job(kind=kind, status="queued", params=params or {}, ref_type=ref_type, ref_id=ref_id)
        db.add(job)
        db.commit()
        job_id = job.id

    def run() -> None:
        with SessionLocal() as db:
            j = db.get(Job, job_id)
            assert j is not None
            j.status, j.started_at = "running", utcnow()
            db.commit()
        try:
            ref = fn(JobContext(job_id))
            with SessionLocal() as db:
                j = db.get(Job, job_id)
                assert j is not None
                j.status, j.progress, j.finished_at = "success", 1.0, utcnow()
                if ref:
                    j.ref_type, j.ref_id = ref
                db.commit()
        except Exception as exc:  # falha registrada no job, não derruba a API
            log.exception("job %s (%s) falhou", job_id, kind)
            with SessionLocal() as db:
                j = db.get(Job, job_id)
                assert j is not None
                j.status, j.finished_at = "failed", utcnow()
                j.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"
                db.commit()

    if sync or get_settings().job_mode == "inline":
        run()
    else:
        fut: Future[None] = executor().submit(run)
        fut.add_done_callback(lambda f: f.exception())
    return job_id
