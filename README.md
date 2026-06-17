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

## Evals de comportamento (sob demanda, fora do CI)

As evals batem na Claude API real e medem o comportamento do modelo (lê número de
volta? recusa dado de outra conta? não inventa saldo?). Ritual e casos em **`EVALS.md`**.

```bash
pytest -m eval                 # precisa de ANTHROPIC_API_KEY no .env; sem ela, skipa
```

O CI roda só a suíte determinística (`-m "not eval"` no `addopts`).

## Subir com Docker (Postgres + app)

```bash
cp .env.example .env       # preencher segredos (Claude, OpenAI, ElevenLabs, Evolution)
bash check-ports.sh        # confirma 8005/8103/5438 livres (padrão da consultoria)
docker compose up --build  # app em http://localhost:8005/health
```

`DATABASE_URL` usa o nome do container (`cb_amc_comercial_db`), nunca `localhost`.
Rodar com **`--workers 1`** (o histórico do MVP é em memória — ver `spec.md`/orchestrator).

Depois de subir, popular o banco e (opcional) cadastrar um cliente-demo — `scripts/`
já vai na imagem:

```bash
docker compose exec app python -m app.data.seed
docker compose exec app python -m scripts.cadastrar_demo --telefone "5547999998888" --nome "Boutique do João"
```

### Deploy na VPS (rede externa da Evolution)

Na VPS o app e o db precisam entrar na rede Docker **externa** onde a Evolution já
roda (`n8n-traefik_app_network`), para que o app alcance a Evolution por
`http://chatbot-imagem-evolution:8080` e a Evolution alcance o nosso webhook por
`http://cb_amc_comercial_app:8000`. Esse ajuste vive no overlay
**`docker-compose.vps.yml`** — aplicado SÓ na VPS, com dois `-f`:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --build
```

O `docker-compose.yml` base fica **dev-safe** (sem rede externa): `docker compose up`
local continua funcionando sem essa rede. O overlay NÃO é um `docker-compose.override.yml`
de propósito — o override seria auto-carregado e quebraria o `up` local (rede externa
inexistente). A rede externa precisa existir antes na VPS (`docker network ls`).

## Conectar o WhatsApp (Evolution) — no host

1. Subir a stack (acima). A Evolution responde na porta `8103`.
2. Criar/conectar a instância (`EVOLUTION_INSTANCE`) e **escanear o QR code** com o
   número **dedicado** (nunca um pessoal — risco de ban; ver `spec.md §11.3`).
3. Apontar o webhook da instância para `POST /webhook/whatsapp` do app (evento
   `messages.upsert`).
4. Preencher `EVOLUTION_API_URL`/`EVOLUTION_API_KEY`/`EVOLUTION_INSTANCE` no `.env`.

### Checklist de validação no host (o que os testes NÃO cobrem — exige Evolution viva)

- [ ] instância conectada; QR escaneado com o número dedicado
- [ ] enviar/receber **texto** num WhatsApp real (ida e volta)
- [ ] enviar/receber **áudio**: nota de voz recebida é transcrita; resposta volta como
      nota de voz (ptt opus) e toca como áudio nativo
- [ ] `DEMO_PHONE` (em `app/data/seed.py`) trocado pelo número real do cliente-demo,
      e o `remoteJid` casa com o `telefone_whatsapp` do seed
- [ ] latência ponta-a-ponta aceitável p/ a demo; mitigações de ban/QR-loop (§11.3)
- [ ] domínio próprio + SSL válido (Traefik) + whitelist com o TI 48h antes (MANIFESTO)

Deploy completo (Traefik, nomes de container, rede externa): **`subir_para_VPS.txt`**.
Operação de demo (contingência A–E, frase-âncora): **`MANIFESTO.md`**.

## Estrutura

```
.
├── app/
│   ├── agent/          # orquestrador (tool-use) + tools + system_prompt.md
│   ├── auth/           # telefone -> cliente_id (fail-closed)
│   ├── data/           # models, repository (filtro por cliente_id), seed, catálogo
│   ├── ops/            # escalonamento (fallback humano)
│   ├── voice/          # stt.py (Whisper) · tts.py (ElevenLabs)
│   ├── whatsapp/       # client.py (Evolution) · router.py (webhook+dispatcher) · factory.py
│   ├── config.py       # Pydantic Settings (segredos só no .env)
│   ├── logging_config.py
│   └── main.py         # FastAPI + /health + webhook
├── tests/              # suíte determinística + tests/evals/ (Claude API real)
├── Dockerfile · docker-compose.yml · requirements*.txt · pyproject.toml
├── EVALS.md            # gate de comportamento
└── .github/workflows/ci.yml
```

O build seguiu o `spec.md §14` — 1 commit atômico por fase, tag `[SNN]`.
