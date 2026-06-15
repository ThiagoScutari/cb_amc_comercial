"""App FastAPI — ponto de entrada (`uvicorn app.main:app`).

Na Fase 0 expõe apenas um health check, suficiente para o container subir e
para o `depends_on: service_healthy` / monitoração. Webhook do WhatsApp e
dispatcher entram na Fase 8.
"""

from fastapi import FastAPI

app = FastAPI(title="cb_amc_comercial", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe simples."""
    return {"status": "ok"}
