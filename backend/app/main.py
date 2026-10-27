from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import analytics, exports, facilities, flows, meta, network, optimization, scenarios, territory, tiles
from app.core.config import get_settings
from app.core.logging import configure_logging

log = logging.getLogger("logitrace.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("LogiTrace API iniciada (%s)", get_settings().env)
    yield


app = FastAPI(
    title="LogiTrace API",
    version="1.0.0",
    description=(
        "Plataforma de inteligência logística e análise territorial do Brasil. "
        "Todos os indicadores informam definição, unidade, período, fonte e limitações; "
        "premissas paramétricas são identificadas explicitamente."
    ),
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=2048)


@app.middleware("http")
async def access_log(request: Request, call_next):  # type: ignore[no-untyped-def]
    t = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t) * 1000
    if not request.url.path.startswith("/api/tiles"):
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, ms)
    response.headers["X-Response-Time-ms"] = f"{ms:.0f}"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"error": {"status": exc.status_code, "message": exc.detail}}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": 422, "message": "Parâmetros inválidos", "details": exc.errors()}}, status_code=422
    )


@app.exception_handler(LookupError)
async def not_found(_: Request, exc: LookupError) -> JSONResponse:
    return JSONResponse({"error": {"status": 404, "message": str(exc).strip("'\"")}}, status_code=404)


@app.exception_handler(ValueError)
async def bad_value(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"error": {"status": 400, "message": str(exc)}}, status_code=400)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("erro não tratado")
    return JSONResponse({"error": {"status": 500, "message": "Erro interno. Consulte os logs do servidor."}}, status_code=500)


for r in (meta, facilities, territory, network, scenarios, optimization, flows, analytics, exports, tiles):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
