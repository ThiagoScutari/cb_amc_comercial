# CLAUDE.md — Chatbot Comercial B2B · AMC (`cb_amc_comercial`)

> Este arquivo é lido no **início de cada sessão**. Ele é o primer enxuto.
> **A fonte da verdade é o `spec.md`.** Leia o `spec.md` por inteiro antes de implementar, e releia a seção correspondente antes de cada fase.
> **Padrões da consultoria** (complementam o spec, seguir sempre): `PORT-REGISTRY.md` (portas), `subir_para_VPS.txt` (deploy Docker+Traefik), `MANIFESTO.md` (operação de demo), `check-ports.sh` (rodar antes de subir).

---

## O que é o projeto (em um parágrafo)

Chatbot de **atendimento comercial B2B** para a AMC Têxtil, via WhatsApp, com **NLP real** e **voz nos dois sentidos** (áudio entra via STT, resposta sai via TTS, voz o mais natural possível). O foco do MVP é **sanar dúvidas** de clientes sobre **pedidos** e **estoque**. Dados em **banco mockado**: produtos reais do catálogo da **Colcci** (marca da própria AMC, via API VTEX); clientes, pedidos e estoque sintéticos. O bot **não executa ações** no sistema da AMC — cancelamento/compra apenas **registram solicitação e avisam o cliente**.

---

## Princípios INVIOLÁVEIS (se violar, o sistema quebra)

1. **O modelo PEDE, o código EXECUTA.** O LLM só gera pedidos de chamada de ferramenta (texto). Quem age é o nosso código. Toda segurança mora **depois** dessa fronteira. *(spec §2.1, §6)*
2. **`cliente_id` vem do CÓDIGO, nunca do modelo.** Toda query de dados filtra pelo `cliente_id` da sessão. Um cliente nunca vê dados de outro (IDOR). *(spec §2.3, §6.3, §7)*
3. **NÃO despejar dados de negócio no contexto do LLM.** A janela guarda as **regras**; a ferramenta busca os **fatos**. Despejar pedidos no contexto vazaria dados entre clientes. **Não copiar o `build_context` do SheetTalk.** *(spec §2.2)*
4. **O bot não executa nada no sistema da AMC.** Cancelamento e compra = **intake**: confirmar dados → registrar solicitação → "registrada, te aviso quando processar". Sem mutar estado. *(spec §1, §6.2)*
5. **Disponibilidade → `saldo`.** "Tem pra comprar?" responde com `saldo` (estoque livre). `disponivel` é controle interno reversível, **não** exposto ao cliente. `reservado` = faturado/despacho. *(spec §5.4, §6.1)*
6. **Texto falável é metade da voz natural.** Respostas em frases curtas, conversacionais, **sem markdown, sem listas, sem bullets** — viram áudio. *(spec §2.5, §8.3, §9)*
7. **Confirmar antes de agir; ler de volta números vindos de áudio** (pedido, quantidade) antes de qualquer intake. *(spec §6.2, §8.1)*

---

## Convenções de trabalho (não-negociáveis)

- **Schema primeiro** — modelo de dados antes de código que o toca.
- **Testes junto com o código** — cada fase entrega testes; **cobertura mínima 70%**. Mentalidade Akita: linhas de teste ≥ linhas de produção.
- **CI em cada commit** (`.github/workflows/ci.yml`): `ruff` → `bandit` → `pip-audit` → `pytest` (rápido, falha cedo). *(spec §15.2)*
- **Todo bug corrigido ganha um teste de regressão** — sem exceção.
- **Commits atômicos** — 1 por fase, mensagem descritiva com tag `[SNN]` (ex.: `feat(data): ... [S01]`).
- **Prompts de LLM em `.md`** — nunca hardcoded (ex.: `app/agent/prompts/system_prompt.md`).
- **Tipagem forte** — SQLAlchemy 2.x + Pydantic v2; sem `dict` solto onde cabe um modelo.
- **Erro explícito** — falha de ferramenta/dados nunca trava o bot: degrada e/ou escala para humano.
- **Segredos no `.env`** — nunca commitar; `.env.example` como template.
- **`ruff check`** sem erros para fechar a fase.

> **Filosofia (Akita):** você (humano) é o arquiteto; o Claude Code é um **dev sênior motivado, não o arquiteto**. Ele tende a over-engineer — corte complexidade desnecessária (YAGNI), revise toda decisão estrutural e **só aprove o que você entende**. Por isso o ritual abaixo: propor antes de implementar.

---

## Como trabalhar (ritual por fase)

Para **cada fase** do plano de build (`spec.md §14`):
1. **Reler** a seção correspondente do `spec.md`.
2. **Propor** em poucas linhas o plano da fase e as decisões-chave (estruturas, contratos). Se houver ambiguidade no spec, **sinalizar e propor duas opções com trade-offs** — não escolher em silêncio.
3. **Implementar** a fase (código + testes).
4. **Validar** (rodar testes; `ruff`; o critério "VALIDAR" da fase).
5. **Commit atômico** com tag `[SNN]`.

Não pular fases. Não misturar módulos no mesmo commit.

---

## Infra: portas e deploy — NÃO improvisar

- **Portas reservadas (PORT-REGISTRY — Claude Code NUNCA escolhe porta):** app `8005:8000`, Evolution `8103:8080`, Postgres `5438:5432`. Projeto **novo** — reservar essas como nova entrada `cb_amc_comercial` no registry. Usar **exatamente** essas no `docker-compose.yml`. Rodar `bash check-ports.sh` antes do primeiro `docker compose up`. *(spec §3.1, §13.1)*
- **Deploy (Docker + Traefik, `subir_para_VPS`):** `Dockerfile`/`compose`/`.env` na **raiz**; base `python:3.12-slim`; CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000`. **Nomes de container únicos**: `cb_amc_comercial_app`/`_db`/`_evolution` (nunca `db`/`api` genéricos). **`DATABASE_URL` usa o nome do container** (`cb_amc_comercial_db`), nunca `localhost`. Healthcheck no Postgres + `depends_on: service_healthy`. Variáveis explícitas no `environment:`. Rede Traefik externa na VPS. *(spec §3.2, §13.1)*
- **Demo é produto (MANIFESTO):** dados pré-carregados e determinísticos (Colcci real + sintéticos), contingência A–E pronta antes, frase-âncora nos 30s, nunca depender de rede/laptop de aliado. *(spec §11.4)*

---

## Stack (referência rápida)

Python 3.12 · FastAPI · Claude API (`AGENT_MODEL=claude-sonnet-4-6`; `ROUTER_MODEL=claude-haiku-4-5-20251001`) · tool use nativo · Whisper STT · **ElevenLabs TTS** · Evolution API (WhatsApp) · PostgreSQL 15 · SQLAlchemy 2.x + Pydantic v2 · pytest · ruff · Docker Compose.
*(detalhes e versões em `spec.md §3`)*

---

## Reuso — de onde copiar (não reinventar)

| Preciso de... | Pegar de |
|---|---|
| `config.py` (Pydantic Settings) | SheetTalk |
| STT (Whisper) | `audio_service.py` do SheetTalk/Camisart |
| esqueleto do agente (carregar prompt `.md`, histórico, `AsyncAnthropic`) | `orchestrator.py` do SheetTalk — **miolo reescrito p/ tool-use** |
| padrão do dispatcher (sessão, histórico, typing, limites) | `handlers.py` do SheetTalk |
| webhook FastAPI + Evolution client + Compose | `chatbot_imagem` |
| estrutura de testes / fixtures | SheetTalk |

**NÃO reusar:** `excel_service.py`, canal Telegram (polling), e o `build_context` de despejo (anti-padrão — princípio 3).
*(mapa completo em `spec.md §4` e §2.1)*

---

## Mapa: para a tarefa X, leia a seção Y do spec

| Tarefa | Seção |
|---|---|
| Modelo de dados / seed | §5 (e §5.6 p/ catálogo Colcci) |
| Ferramentas / function calling | §6 |
| Identificação e segurança | §7 |
| Voz (STT/TTS/falável) | §8 |
| System prompt / persona | §9 |
| Fluxos e casos de eval | §10 |
| Fallback e riscos Evolution | §11 |
| Estrutura de pastas | §13 |
| **Plano de build (fase a fase)** | **§14** |
| Decisões já fechadas | §16 |

---

## Lembretes pontuais

- **Catálogo Colcci (VTEX):** usar a **API pública** (`/api/catalog_system/pub/products/search`), não raspar HTML (tem anti-bot). **Validar o endpoint com o RefId `360118439`** na Fase 1b antes de popular em lote. Cachear o JSON em `tests/fixtures/colcci_products.json`. *(spec §5.6)*
- **Código de produto Colcci:** 9 dígitos = `[categoria 2][marca 2][ordem 5]` (ex.: `36`=Blusa Feminina, `01`=Colcci, `18439`=ordem).
- **ElevenLabs:** o onboarding (API key, `voice_id`) será fornecido na Fase 7 — pedir antes de codar o TTS.
- **Identificação por telefone** pode subir de nível depois — deixar `auth/session.py` extensível.
- **Decisões em default (🟡)** ainda abertas: modelo no caminho fácil (Haiku por eval) — `spec.md §16`.

---

*Leia o `spec.md`. Não viole os princípios acima. Proponha antes de implementar cada fase.*
