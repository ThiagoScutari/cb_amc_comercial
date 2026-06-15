# cb_amc_comercial

Chatbot de **atendimento comercial B2B** da AMC Têxtil (Oasis Resortwear) via WhatsApp,
com NLP real e voz nos dois sentidos (STT na entrada, TTS na saída). MVP focado em
**sanar dúvidas** sobre pedidos e estoque. Dados mockados (produtos reais da Colcci via
API VTEX; clientes/pedidos/estoque sintéticos). O bot **não executa ações** no sistema da
AMC — cancelamento/compra apenas registram solicitação e avisam o cliente.

> Fonte da verdade: **`spec.md`**. Primer de sessão: **`CLAUDE.md`**.

## Stack

Python 3.12 · FastAPI · Claude API · Whisper (STT) · ElevenLabs (TTS) · Evolution API
(WhatsApp) · PostgreSQL 15 · SQLAlchemy 2.x + Pydantic v2 · pytest · ruff · Docker Compose.

## Portas reservadas (PORT-REGISTRY — não improvisar)

| Serviço      | host:container |
|--------------|----------------|
| FastAPI app  | `8005:8000`    |
| Evolution    | `8103:8080`    |
| PostgreSQL   | `5438:5432`    |

## Desenvolvimento local

Requer Python 3.12+.

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env                                # preencher segredos

# Qualidade (mesma ordem do CI)
ruff check . && ruff format --check .
bandit -r app/
pip-audit -r requirements.txt
pytest                                              # cobertura mínima 70%
```

## Subir com Docker (Postgres + app)

```bash
bash check-ports.sh        # confirma 8005/8103/5438 livres (padrão da consultoria)
docker compose up --build  # app em http://localhost:8005/health
```

`DATABASE_URL` usa o nome do container (`cb_amc_comercial_db`), nunca `localhost`.

## Estrutura (Fase 0)

```
.
├── app/
│   ├── config.py      # Pydantic Settings
│   └── main.py        # FastAPI + /health
├── tests/             # pytest (config + health)
├── Dockerfile         # python:3.12-slim
├── docker-compose.yml # db + app, portas fixas, volume nomeado, healthcheck
├── requirements.txt   # runtime  ·  requirements-dev.txt  # dev/CI
├── pyproject.toml     # config ruff/pytest/coverage/mypy/bandit
└── .github/workflows/ci.yml
```

As demais fases (modelo de dados, ingestão Colcci, agente, voz, WhatsApp) seguem o
plano de build do `spec.md §14` — 1 commit atômico por fase, tag `[SNN]`.
