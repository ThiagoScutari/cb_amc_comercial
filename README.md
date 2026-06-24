# Atendente Comercial AMC — Chatbot B2B no WhatsApp

[![CI](https://github.com/ThiagoScutari/cb_amc_comercial/actions/workflows/ci.yml/badge.svg)](https://github.com/ThiagoScutari/cb_amc_comercial/actions/workflows/ci.yml)

> **Status:** MVP / demonstração. Banco mockado — catálogo **Colcci real**; clientes,
> pedidos e estoque **sintéticos**. Projeto de consultoria (sem licença pública).

Assistente de **atendimento comercial B2B** da AMC Têxtil que conversa com lojistas e
compradores pelo **WhatsApp** e responde, em **texto e áudio**, sobre **pedidos** e
**disponibilidade de estoque** — entendendo a pergunta em linguagem natural, sem menus
nem formulários.

---

## O que ele faz

- **Atende no WhatsApp, a qualquer hora, sem fila.** O cliente manda a mensagem e é
  respondido na hora, como numa conversa normal.
- **Entende linguagem natural — por escrito ou por voz.** O cliente pode digitar ou
  **mandar uma mensagem de voz**; o assistente entende as duas formas.
- **Responde no mesmo canal da pergunta.** Quem **escreve** recebe **texto**; quem manda
  **áudio** recebe a resposta como **nota de voz inline** (sem repetir o texto longo). Se a
  voz falhar, cai de volta para texto — o bot nunca fica mudo.
- **Consulta pedidos, estoque e catálogo.** Status e prazo de um pedido, se um produto
  está disponível para comprar, e busca no catálogo (*"tem camiseta branca M?"*).
- **Informa a condição de pagamento da conta.** Responde *"qual a minha condição de
  pagamento?"* com os dados comerciais da própria conta.
- **Monta um resumo visual em PDF.** A pedido (*"meus pedidos"*, *"minhas notas"*, *"meus
  boletos"*, *"minhas devoluções"*), além da resposta, envia um **documento PDF** com a lista
  — pedidos, notas fiscais, títulos ou devoluções.
- **Não deixa o cliente no vácuo.** Quando a consulta demora um pouco, ele avisa
  *"só um instante, já estou verificando"* antes de trazer a resposta.
- **Cada cliente vê só os próprios dados.** Uma conta nunca enxerga pedidos ou
  informações de outra (isolamento por segurança).
- **Não executa ações sozinho.** Pedidos de cancelamento ou de compra não são
  executados: o assistente **registra a solicitação e encaminha** ao time, avisando o
  cliente de que o time retorna.

![Fluxo de atendimento](docs/img/fluxo.png)

Quando a resposta exige uma consulta mais demorada, o cliente recebe um aviso
intermediário para não ficar esperando em silêncio:

![Resposta intermediária](docs/img/ack.png)

---

## Como funciona

O cliente fala pelo WhatsApp; a mensagem chega ao nosso serviço pela **API oficial do
WhatsApp (Meta)**. Se for áudio, ele é **transcrito** para texto; um modelo de
linguagem **(Claude)** interpreta o pedido e, quando precisa de um dado real (pedido,
prazo, estoque), o **código** — não o modelo — consulta a base e devolve o fato. A
resposta volta **pelo mesmo canal da pergunta**: quem escreveu recebe texto, quem mandou
áudio recebe uma **nota de voz**. Quando há um resumo visual, um **PDF** acompanha a
resposta nos dois casos.

![Arquitetura](docs/img/arquitetura.png)

**Stack:** WhatsApp Cloud API (Meta/Graph) · Claude (Anthropic) · Whisper/OpenAI (voz →
texto) · ElevenLabs (texto → voz) · PostgreSQL · FastAPI (Python 3.12).

**Sobre os dados (transparência):** o **catálogo de produtos é real** — itens da
**Colcci** (marca da própria AMC), obtidos via API VTEX. Já **clientes, pedidos e
estoque são sintéticos** (dados de demonstração). O assistente é **somente-leitura**:
não altera nada no sistema da AMC.

---

## Documentação técnica

> Fonte da verdade do produto: **`spec.md`**. Primer de cada sessão de
> desenvolvimento: **`CLAUDE.md`**.

**Nesta seção:** [Portas reservadas](#portas-reservadas-port-registry--não-improvisar) ·
[Desenvolvimento local](#desenvolvimento-local) ·
[Evals](#evals-de-comportamento-sob-demanda-fora-do-ci) ·
[Docker](#subir-com-docker-postgres--app) ·
[Deploy na VPS](#deploy-na-vps-traefik) ·
[Conectar o WhatsApp](#conectar-o-whatsapp-cloud-api-da-meta) ·
[Estrutura](#estrutura)

### Portas reservadas (PORT-REGISTRY — não improvisar)

| Serviço     | host:container |
|-------------|----------------|
| FastAPI app | `8005:8000`    |
| PostgreSQL  | `5438:5432`    |

### Desenvolvimento local

Requer Python 3.12+.

> **Dependência de sistema (relatório PDF):** o WeasyPrint exige libs nativas (Pango, Cairo,
> GDK-PixBuf). No container elas já vão no `Dockerfile`; rodando **fora** do container,
> instale-as pelo SO — no Debian/Ubuntu: `libpango-1.0-0 libpangocairo-1.0-0 libcairo2
> libgdk-pixbuf-2.0-0 libffi8`. Sem elas, a geração do PDF falha (mas degrada: o texto/áudio
> sai do mesmo jeito).

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

> Os testes de IDOR marcados `@pytest.mark.postgres` sobem um Postgres efêmero
> (testcontainers) e **exigem Docker** — sem Docker, pulam automaticamente.

### Evals de comportamento (sob demanda, fora do CI)

As evals batem na Claude API real e medem o comportamento do modelo (lê número de volta?
recusa dado de outra conta? não inventa saldo?). Ritual e casos em **`EVALS.md`**.

```bash
pytest -m eval                 # precisa de ANTHROPIC_API_KEY no .env; sem ela, skipa
```

O CI roda só a suíte determinística (`-m "not eval"` no `addopts` do `pyproject.toml`).

### Subir com Docker (Postgres + app)

```bash
cp .env.example .env       # preencher segredos (Claude, OpenAI, ElevenLabs, WhatsApp)
docker compose up --build  # app em http://localhost:8005/health
```

Garanta que as portas **8005** (app) e **5438** (Postgres) estejam livres no host antes
de subir. O `DATABASE_URL` usa o nome do container (`cb_amc_comercial_db`), nunca
`localhost`. Rode com **`--workers 1`** — o histórico de conversa do MVP é em memória
(ver `spec.md` / `app/agent/orchestrator.py`).

Depois de subir, popular o banco e (opcional) cadastrar um cliente-demo extra — `scripts/`
já vai na imagem:

```bash
docker compose exec app python -m app.data.seed
docker compose exec app python -m scripts.cadastrar_demo --telefone "5547999998888" --nome "Boutique do João"
```

O **seed** cria os **3 clientes-demo** (`{1,2,3}` — Boutique Aurora, Maré Alta, Debora Modas)
com pedidos, estoque e **fiscal** (notas fiscais, títulos, devoluções). Os telefones desses
clientes vêm de **`DEMO_PHONE_1/2/3`** no `.env`: na VPS, os números **reais** de WhatsApp; em
dev/CI, deixe **em branco** e o seed usa defaults fictícios determinísticos (os testes assumem
esses defaults). O `cadastrar_demo` cria um cliente extra sob demanda — **também com fiscal**,
em faixa de numeração própria que não colide com o seed.

### Deploy na VPS (Traefik)

Na VPS, app e banco entram na rede Docker **externa** do Traefik
(`n8n-traefik_app_network`) para que o Traefik publique o app em
`https://bot.thiagoscutari.com.br` com TLS. Esse ajuste vive no overlay
**`docker-compose.vps.yml`**, aplicado SÓ na VPS com dois `-f`:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --build
```

> **Pós-S18c:** o `--build` reconstrói a imagem instalando as **libs de sistema do WeasyPrint**
> (Pango/Cairo/…) — a primeira build após essa mudança é mais pesada; as seguintes usam cache.
> Reaplique o seed só se o schema/dados mudaram (`docker compose exec app python -m app.data.seed`).

O `docker-compose.yml` base é **dev-safe** (sem rede externa), então `docker compose up`
local continua funcionando. O overlay **não** é um `docker-compose.override.yml` de
propósito: o override seria auto-carregado e quebraria o `up` local (a rede externa não
existe na máquina de dev). A rede externa precisa existir antes na VPS
(`docker network ls`).

### Conectar o WhatsApp (Cloud API da Meta)

A integração é com a **WhatsApp Cloud API oficial** (Graph API) — **não há QR code**. O
mesmo path `/webhook/whatsapp` atende dois momentos:

1. **Verificação do webhook (GET).** No app da Meta, configure a *Callback URL*
   `https://bot.thiagoscutari.com.br/webhook/whatsapp` e o *Verify Token* igual a
   `WHATSAPP_VERIFY_TOKEN`. A Meta faz um GET com `hub.verify_token`/`hub.challenge`; o
   app confere o token e devolve o challenge.
2. **Recebimento de mensagens (POST).** A Meta envia os eventos em
   `entry[].changes[].value.messages[]`. Cada POST é autenticado pela assinatura
   `X-Hub-Signature-256` (HMAC-SHA256 do corpo com o `WHATSAPP_APP_SECRET`), validada
   antes de qualquer parse. Se o `WHATSAPP_APP_SECRET` estiver **vazio**, a validação é
   **pulada** (com aviso no log) para não travar dev/demo — **preencha-o antes de ir a
   produção**.

Para a Meta **entregar** mensagens, a conta WhatsApp Business (**WABA**) precisa estar
**inscrita no app** (`subscribed_apps`) — sem isso, o webhook nunca recebe nada. O envio
de respostas usa o **número da Meta** (`WHATSAPP_PHONE_NUMBER_ID`) e um **token
permanente** de System User (`WHATSAPP_ACCESS_TOKEN`).

Variáveis relevantes no `.env` (template em `.env.example`):

| Variável | Para quê |
|----------|----------|
| `WHATSAPP_WABA_ID`         | conta WhatsApp Business; usada p/ inscrever a WABA no app (`subscribed_apps`) |
| `WHATSAPP_PHONE_NUMBER_ID` | número virtual da Meta que envia/recebe |
| `WHATSAPP_ACCESS_TOKEN`    | token permanente (System User) |
| `WHATSAPP_VERIFY_TOKEN`    | string que você define; verificação do webhook (GET) |
| `WHATSAPP_APP_SECRET`      | valida a assinatura `X-Hub-Signature-256` (POST) |
| `WHATSAPP_API_VERSION`     | versão do Graph API (ex.: `v23.0`) |

> Migração: o projeto **nasceu sobre a Evolution API** (não-oficial) e **migrou para a
> Cloud API oficial da Meta**. As variáveis `EVOLUTION_*` permanecem apenas comentadas,
> como caminho de rollback — não fazem parte do fluxo atual.

#### Checklist de validação no host (o que os testes NÃO cobrem — exige número real)

- [ ] webhook verificado na Meta (GET com o `WHATSAPP_VERIFY_TOKEN` retorna o challenge)
- [ ] WABA inscrita no app (`subscribed_apps`) — mensagens chegando no `POST /webhook/whatsapp`
- [ ] enviar/receber **texto** num WhatsApp real (ida e volta)
- [ ] enviar **áudio**: a voz é transcrita e o bot responde como **nota de voz inline**
      (não um arquivo para baixar) — e o texto longo **não** acompanha o áudio
- [ ] `DEMO_PHONE_1/2/3` no `.env` trocados pelos números reais dos 3 clientes-demo
- [ ] **resumo visual:** mandar "meus pedidos" (ou "minhas notas"/"meus boletos"/"minhas
      devoluções") e confirmar que chega o **PDF** da lista — é aditivo: se falhar, a
      resposta (texto ou áudio) sai do mesmo jeito
- [ ] domínio próprio + SSL válido (Traefik) ativos em `bot.thiagoscutari.com.br`

### Estrutura

```
.
├── app/
│   ├── agent/          # orquestrador (tool-use) + tools + system_prompt.md
│   ├── auth/           # telefone -> cliente_id (fail-closed)
│   ├── data/           # models, repository (filtro por cliente_id), seed, catálogo
│   ├── ops/            # escalonamento (fallback humano)
│   ├── report/         # resumo visual em PDF — pedidos/NF/título/devolução (WeasyPrint, aditivo)
│   ├── voice/          # stt.py (Whisper) · tts.py (ElevenLabs) · fala.py (texto falável)
│   ├── whatsapp/       # client.py (Cloud API) · router.py (webhook+dispatcher) · factory.py
│   ├── config.py       # Pydantic Settings (segredos só no .env)
│   ├── logging_config.py
│   └── main.py         # FastAPI + /health + webhook
├── tests/              # suíte determinística + tests/evals/ (Claude API real)
├── scripts/            # operacionais (cadastrar_demo, captura do catálogo Colcci)
├── docs/img/           # diagramas do README
├── Dockerfile · docker-compose.yml · docker-compose.vps.yml · requirements*.txt · pyproject.toml
├── EVALS.md            # gate de comportamento
├── spec.md · CLAUDE.md
└── .github/workflows/ci.yml
```

O build seguiu o `spec.md §14` — 1 commit atômico por fase, tag `[SNN]`.
