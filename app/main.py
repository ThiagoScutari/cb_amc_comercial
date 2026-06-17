"""App FastAPI — ponto de entrada (`uvicorn app.main:app --workers 1`).

Health check (Fase 0) + webhook do WhatsApp e dispatcher (Fase 8). O `Dispatcher`
(clients reais, keys de settings) é montado no LIFESPAN e guardado em
`app.state.dispatcher`; o webhook o lê de lá. Se a montagem falhar (sem .env/deps no
dev), o app SOBE mesmo assim — o health continua vivo e o webhook ignora — em vez de
derrubar o processo.

DÍVIDA CONSCIENTE (multi-worker): `HistoricoMemoria` é um dict em processo — num deploy
multi-worker o histórico não é compartilhado. Por isso `--workers 1` no MVP; trocar por
impl Postgres (mesma interface `HistoricoStore`) antes de escalar. (Ver orchestrator.py.)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.whatsapp.router import criar_router

logger = logging.getLogger("cb_amc_comercial.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.whatsapp.factory import criar_dispatcher

        app.state.dispatcher = criar_dispatcher()
    except Exception as exc:  # noqa: BLE001 - sem .env/deps: sobe assim mesmo (health vive; webhook ignora)
        logger.warning("dispatcher não inicializado: %s", str(exc)[:160])
        app.state.dispatcher = None
    yield
    disp = getattr(app.state, "dispatcher", None)
    if disp is not None:
        await disp.aclose()


app = FastAPI(title="cb_amc_comercial", version="0.1.0", lifespan=lifespan)
app.state.dispatcher = None  # default seguro antes do lifespan / em testes
app.include_router(criar_router())


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe simples."""
    return {"status": "ok"}
