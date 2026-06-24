# spec.md — Chatbot Comercial B2B · Oasis Resortwear (AMC)
## Contexto-mestre para o Claude Code

**Cliente:** Oasis Resortwear — marca do grupo **AMC Têxtil** (contato: **Luis**, gerente de TI)
**Nome do projeto / pasta:** `cb_amc_comercial` — **projeto novo**, sem relação com outros. Portas a reservar como nova entrada no `PORT-REGISTRY` (app 8005 / Evolution 8103 / Postgres 5438).
**Consultoria:** Thiago Scutari Consultoria
**Versão:** 2.5
**Data:** Junho 2026
**Changelog v2.5:** sprints **S17–S19** (enriquecimento do mock + refinamentos do teste real na VPS). **S17a:** roster enxuto para 3 clientes `{1,2,3}` (Boutique Aurora/Maré Alta/Debora Modas) e telefones via env (`DEMO_PHONE_1/2/3`, defaults fictícios determinísticos; reais só na VPS). **S17b:** pedidos engordados com grade realista (5–10 SKUs distintos por pedido) + fiscal (NF/título/devolução, faixa 90xxx) no `scripts/cadastrar_demo`; **E2** reescrito determinístico. **S17c:** desambiguação de NOME de empresa no `system_prompt` (identidade SEMPRE pelo telefone; não rotular dados próprios com nome citado; sem recusa cega) — restaura E4 a 100% honesto. **S18a:** normalização texto→fala robusta (`fala.py`) — valores de milhão/bilhão por extenso e filtro de códigos não-vocalizáveis (linha digitável/chave/rastreio → frase curta, só no áudio), blindagem por token. **S18b:** áudio como **nota de voz inline** (`voice: true` + OGG/OPUS mono). **S18c:** relatório visual passa a **PDF via WeasyPrint** — a Cloud API oficial rejeita `text/html` como documento (ADR-0003); `pydyf` pinado, libs apt no Dockerfile, grid trocado por `inline-block`. **S19a:** valores falados **cheios** com centavo **truncado** ("cerca de" só quando trunca) e **números de documento audíveis** (cardinal sem zero interno; dígito-a-dígito com zero interno, por palavra-chave). **S19b:** **mensagens por canal** — texto-in → texto+PDF; áudio-in → áudio+PDF (sem o texto longo redundante), com fallback obrigatório a texto se o TTS falhar (nunca mudo). Segurança estrutural (E8 IDOR) a **100%**; suíte determinística verde (311 testes).
**Changelog v2.4:** sprint **S11–S16** (entidades fiscais + cópia visual). **S11:** entidades `NotaFiscal`/`Titulo`/`Devolucao` + 3 enums (`StatusEntrega`/`StatusTitulo`/`StatusDevolucao`); CHECK só nos enums fiscais (ADR-0001). **S12:** seed determinístico das fiscais (NF 60001+, título 70001+, devolução 80001+), crédito INTEGRAL na devolução `credito_gerado`, 3 devoluções cobrindo o lifecycle (aguardando/expirado/crédito) e cobertura cross-client. **S13:** repository read-only anti-IDOR (`cliente_id` 1º parâmetro, filtro direto na coluna) + `consultar_faturamento`; IDOR das fiscais testado em Postgres real. **S13b:** busca de cor tolerante a gênero ("branca"→"Branco") DERIVADA do fixture, zero falso positivo. **S14:** 7 tools read-only + Views (8→15 tools), `cliente_id` nunca no schema. **S15a:** ESCOPO de NF/título/devolução/faturamento no `system_prompt` + read-back de número de NF/título; cancelamento REGISTRA no "sim" (motivo opcional, depois). **S15b:** evals **E8a/b/c** (IDOR fiscal, 100%, N=10, dois níveis) + **E9a-d** (comportamento das tools novas); **E2** robusto a N=10. **S16:** cópia visual por LISTAS (pedido/NF/título/devolução), refactor com base reutilizável (`_SHELL`) e saída de pedidos **byte-idêntica** (Caminho A; 2ª via individual adiada — ADR-0002). Toda a segurança (E4/E5/E8) a **100%**; suíte de eval com **14 casos**; 280 testes determinísticos verdes. Dívida registrada: uniformizar CHECK dos enums legados (ADR-0001) e a 2ª via individual (Caminho C, ADR-0002).
**Changelog v2.3:** Fases 7 (TTS ElevenLabs) e 8 (webhook+dispatcher ponta a ponta) fechadas — integração completa, 139 testes. §7.2: registrada a dívida de segurança consciente do webhook (POST público sem auth no MVP; shared-secret na V2). Pendência de host: DEMO_PHONE real no seed, conexão Evolution.
**Changelog v2.2:** consistência interna — removidas referências obsoletas a `categoria_cod` fora dos changelogs (§5.6 e plano de build agora usam `tipo_cod`/âncora-direita, alinhados à regra v1.9). Fase 6 (STT) fechada.
**Changelog v2.1:** Fases 4 e 5 fechadas (agente tool-use + intake read-only, IDOR de escrita e não-mutação testados). §11.4: registrado o risco de demo do STT/TTS (única dependência de rede externa ao vivo na voz) com plano B obrigatório = texto no mesmo loop.
**Changelog v2.0:** Fase 1 (modelo+catálogo+seed) fechada e verde (47 testes). Exemplos do §10 alinhados aos SKUs REAIS do seed (camiseta branca M 340103413; bermuda bege 30103321) — não inventar produto fora do fixture; demo roda sobre dado real. Pendências à parte: acessórios/Unissex (re-captura) e telefone do cliente-demo (DEMO_PHONE, Fase 8).
**Changelog v1.9:** RefId 100% confirmado pelo cliente (com exemplo real `340103413`=Camiseta fem Colcci). Regra definitiva: ref = 10 díg. internos (tipo 3 + marca 2 + ordem 5), site corta zeros à esquerda; parse ancora pela direita e o `tipo_cod` recebe `zfill(3)` como ÚLTIMA etapa (resto→001–999). `034` e `344` não colidem. Sem pendência de parse com o Luis (só o significado textual dos tipos).
**Changelog v1.8:** estrutura real do RefId confirmada pelo cliente: **`TTT.MM.NNNNN`** (tipo 1–3 díg. + marca 2 + ordem 5), site sem pontos e sem zeros à esquerda. Parser deve **ancorar pela direita** (ordem=últimos 5, marca=2 antes, tipo=resto). O parse 2+2+5 do S01 estava errado. `categoria_cod`→`tipo_cod`(3); tipo codifica peça+gênero. Marca embute AMC (01 Colcci, 14 Triton, 46 Forum).
**Changelog v1.7:** API VTEX da Colcci validada como INDISPONÍVEL (403/302→busca). Fonte do catálogo mudou para **scraping via Firecrawl → fixture** (§5.6 reescrita). Achado: `ref_produto` não é sempre 9 díg. (tops 9, bottoms 8) → `categoria_cod`/`marca_cod`/`ordem` agora **nullable**; +`genero`/+`categoria_txt` no modelo. Fase 1b reescrita (captura+loader). Pendência: pedir ao Luis a estrutura do ref de 8 díg. e/ou export oficial.
**Changelog v1.6:** incorporadas as práticas de Vibe Coding do **Fábio Akita** (§15.1) e o **pipeline de CI** (§15.2), adaptando as ferramentas Rails→Python (RuboCop→ruff, Brakeman→bandit, bundler-audit→pip-audit, SimpleCov→pytest-cov). CI (`.github/workflows/ci.yml`) entra na Fase 0. Regras: IA é dev sênior (não arquiteto), todo bug ganha teste de regressão, linhas de teste ≥ produção.
**Changelog v1.5:** correção — `cb_amc_comercial` é projeto **novo**, sem portas registradas. Alocadas as **próximas livres** do PORT-REGISTRY: app **8005** / Evolution **8103** / Postgres **5438** (a entrada "Chatbot Oasis Resortwear (AMC)" 8002/8102/5434 é de outro projeto). Reservar a nova entrada no registry.
**Changelog v1.4:** nome do projeto reconciliado para **`cb_amc_comercial`** (pasta, containers `cb_amc_comercial_app/db/evolution`, DB, instância Evolution) — mantendo a reserva de portas registrada como "Chatbot Oasis Resortwear (AMC)".
**Changelog v1.3:** cliente esclarecido (Oasis Resortwear, marca AMC; Luis = gerente de TI). **Portas reservadas** do PORT-REGISTRY fixadas (app 8002 / Evolution 8102 / Postgres 5434) — Claude Code nunca escolhe porta. Padrão de deploy Traefik (subir_para_VPS) e nomes de container únicos incorporados. Demo segue o MANIFESTO (mesmo cliente da demo do CatalogFlow que falhou em 04/06).
**Changelog v1.2:** produtos do mock vêm do catálogo real da **Colcci** (marca da própria AMC Têxtil) via **API pública VTEX** — dado autêntico, não scraping de terceiro. Estrutura do código de produto (categoria+marca+ordem) incorporada. Fase 1 dividida em 1/1b/1c (modelos → ingestão Colcci → seed).
**Changelog v1.1:** premissas confirmadas pelo Thiago. MVP **focado em sanar dúvidas** (leitura). O bot **não executa nenhuma ação** no sistema da AMC — escrita = registrar solicitação + avisar o cliente. Estoque: "disponível para comprar" = `saldo`; `disponivel` é controle interno reversível. Identificação vinculada ao telefone. TTS = ElevenLabs (fixo).
**Propósito deste documento:** este é o **contexto-mestre** do projeto. O Claude Code deve lê-lo por inteiro antes de qualquer implementação e consultá-lo durante todo o desenvolvimento. Ele contém o objetivo, os princípios de design (não-negociáveis), o modelo de dados, os contratos das ferramentas, a arquitetura de voz, as regras de segurança, o plano de build fase-a-fase e as convenções de trabalho.

> **Padrões da consultoria (na raiz do projeto, seguir sempre):** `PORT-REGISTRY.md` (portas — fonte da verdade), `subir_para_VPS.txt` (deploy Docker+Traefik), `MANIFESTO.md` (operação de demo/campo), `check-ports.sh` (rodar antes de subir). Estes complementam este spec.

> **Como ler:** seções 1–3 são o "porquê" e as regras invioláveis. Seções 4–12 são a especificação técnica. Seção 13 é a estrutura de pastas. Seção 14 é o plano de build executável (fase a fase, 1 commit por fase). Seção 15 são as convenções. Seção 16 registra o status das decisões (resolvidas e defaults).

---

## 1. Objetivo e contexto

Construir um **chatbot de atendimento comercial B2B** para a AMC Têxtil, com **NLP real**, que aceita **texto e áudio** na entrada e responde em **texto e áudio**, com voz **o mais natural possível**. O canal inicial é WhatsApp.

O bot atende **clientes B2B** (lojistas/compradores). O **foco central do MVP é sanar dúvidas** sobre pedidos e estoque (leitura). Capacidades:
- **Pedidos** — status, conteúdo, prazo de entrega *(leitura)*
- **Disponibilidade de produtos** em estoque *(leitura)*
- **Solicitação de cancelamento** de pedido *(intake — registra e avisa; não executa)*
- **Solicitação de compra / novo pedido** *(intake — registra e avisa; não executa)*

> **Regra de ouro do MVP:** o bot **não executa nenhuma ação** no sistema da AMC. Ele responde dúvidas e, quando o cliente quer cancelar ou comprar, **confirma os dados, registra a solicitação e avisa que ela ficou registrada** — informando que assim que a AMC processar, o cliente será notificado. Quem executa é um humano, fora do bot.

> **Tópico × ação:** o bot **pode conversar** sobre temas como pagamento, financeiro, nota fiscal e logística *quando houver dado disponível para informar* (ex.: condição de pagamento do cliente, se o pedido está faturado, prazo de entrega). O que está fora de escopo é **executar ações** nesses temas — isso o bot nunca faz.

No MVP, os dados vêm de um **banco mockado** (sem ERP real ainda), modelado para que a troca futura pelo ERP da AMC seja trocar a implementação da camada de dados sem tocar no agente.

### 1.1 O que está FORA do escopo do MVP
- Integração com o ERP real da AMC (banco mockado simula o ERP)
- **Executar** qualquer ação no sistema da AMC — cancelamento, faturamento, criação de pedido (o bot só **registra a solicitação e avisa**; humano executa)
- **Executar** ações de pagamento, financeiro, nota fiscal ou logística (conversar/informar sobre esses temas é permitido onde houver dado; executar não)
- Multicanal (começa só no WhatsApp)
- Dados pessoais reais de clientes no piloto (dados mockados)

Qualquer item fora desta lista vira nova proposta/sprint. Escopo que cresce no meio do desenvolvimento mata prazo e margem.

---

## 2. Princípios de design — NÃO-NEGOCIÁVEIS

Estes princípios vêm do estudo do projeto (`chatbot_estudo.md`) e governam toda decisão técnica. O Claude Code não deve violá-los, mesmo que pareça mais simples.

### 2.1 O modelo PEDE, o código EXECUTA (Módulo 7)
O LLM **só gera texto**. Ele nunca executa uma ação: ele gera um *pedido de chamada de ferramenta* (texto estruturado), e o **nosso código** lê esse pedido, valida, e executa a ação real contra o banco. Toda a segurança mora **depois** dessa fronteira, no código.

### 2.2 A janela guarda as REGRAS; a ferramenta busca os FATOS (Módulos 5 e 7)
**Proibido despejar dados de negócio no contexto do LLM.** Nada de carregar todos os pedidos/estoque no prompt. O System Prompt carrega só as *regras*; os *fatos* (pedido X, saldo do produto Y) são buscados sob demanda via function calling. Isso é obrigatório por três razões: custo, qualidade (lost-in-the-middle) e — decisivo aqui — **isolamento de dados entre clientes** (ver 2.3).

> ⚠️ **Anti-padrão herdado a NÃO copiar:** o SheetTalk usa `build_context` para despejar a planilha inteira no prompt. Isso **não** pode ser replicado aqui: num cenário multicliente, despejar pedidos no contexto vazaria dados de um cliente enquanto atende outro (IDOR via contexto).

### 2.3 `cliente_id` vem do CÓDIGO, nunca do modelo (segurança)
O cliente é identificado pelo **código** (telefone → `cliente_id`) **antes** de o agente rodar. Toda ferramenta de dados usa esse `cliente_id` da sessão. O modelo pode pedir `consultar_pedido(numero=4471)`, mas é o código que injeta o `cliente_id` e **verifica que o pedido pertence àquele cliente**. Isso previne IDOR — um cliente nunca vê dados de outro. **Trate o modelo como potencialmente comprometido:** mesmo que uma injeção convença o modelo a pedir o dado errado, a checagem no código segura o dano.

### 2.4 Leitura antes de escrita; confirmar antes de agir (Módulo 7)
Ações de **leitura** são seguras e diretas. Ações de **escrita** (cancelamento, compra) **sempre** confirmam com o cliente antes e passam pela camada de permissão no código.

### 2.5 Texto "falável" é metade da voz natural (Módulos 6 e 9)
"Voz o mais real possível" depende **tanto** do TTS **quanto** do texto que o agente gera. O System Prompt obriga respostas em frases curtas, tom de conversa, **sem markdown, sem listas, sem bullets** — porque a resposta vira áudio.

### 2.6 Schema primeiro; testes junto com o código; commits atômicos
Modelo de dados antes de qualquer código. Todo módulo nasce com seus testes (mínimo 70% de cobertura). 1 commit atômico por fase, com tag `[SNN]`. Prompts de LLM em arquivos `.md` separados, nunca hardcoded.

---

## 3. Stack tecnológica (versões fixas)

| Camada | Tecnologia | Observação |
|---|---|---|
| Linguagem | Python 3.12 | |
| Backend/API | FastAPI | webhook do WhatsApp (herdado do `chatbot_imagem`) |
| Agente LLM | Claude API (`anthropic`, `AsyncAnthropic`) | `claude-sonnet-4-6` (agente); avaliar `claude-haiku-4-5` no caminho fácil por eval |
| Function calling | Tool use nativo da Claude API | núcleo do sistema |
| STT (áudio→texto) | Whisper (`openai`, `whisper-1`) | reuso do `audio_service.py` do SheetTalk/Camisart |
| TTS (texto→áudio) | **ElevenLabs** (confirmado) | voz PT-BR natural; onboarding (cadastro/token/voice_id) na Fase 7 |
| WhatsApp | Evolution API | herdado; atenção aos riscos operacionais (seção 11) |
| Banco | PostgreSQL 15 | mockado no MVP; modelado p/ espelhar o ERP futuro |
| ORM | SQLAlchemy 2.x + Pydantic v2 | tipagem forte |
| Config | `pydantic-settings` (BaseSettings) | reuso do `config.py` do SheetTalk |
| Templates | Jinja2 | relatórios/painel opcionais |
| Testes | pytest + pytest-asyncio + pytest-cov | mínimo 70% |
| Lint | ruff | 0 erros para fechar fase |
| Containerização | Docker Compose | herdado |

> Sobre custo/preço por token: **não cravar número no código nem no spec** — preço é consulta no momento da decisão (Módulo 10). O durável é o método de modelar a conta.

### 3.1 Portas reservadas (PORT-REGISTRY) — NÃO deixar o Claude Code decidir

Este é um **projeto novo**, sem portas previamente registradas. As próximas portas livres do `PORT-REGISTRY.md` (tabela "Próximas disponíveis") foram alocadas para ele e **devem ser reservadas no registry como nova entrada `cb_amc_comercial`** (não confundir com a entrada "Chatbot Oasis Resortwear (AMC)", que é outro projeto e já tem 8002/8102/5434). Portas **fixas** deste projeto:

| Serviço | Porta host:container | Reserva |
|---|---|---|
| FastAPI app | `8005:8000` | a reservar |
| Evolution API (WhatsApp) | `8103:8080` | a reservar |
| PostgreSQL | `5438:5432` | a reservar |

**Obrigatório (procedimento da consultoria):**
- Rodar `bash check-ports.sh` **antes** do primeiro `docker compose up` (confirma que 8005/8103/5438 estão livres).
- Usar **exatamente** essas portas no `docker-compose.yml` — não inventar.
- Portas internas dos containers (`8000` app, `8080` Evolution, `5432` Postgres) nunca são publicadas diretamente.

### 3.2 Padrão de deploy (Docker + Traefik) — `subir_para_VPS`

O `docker-compose.yml` segue o padrão blindado da consultoria (`subir_para_VPS.txt`):
- **Nomes de container únicos** com prefixo do projeto: `cb_amc_comercial_app`, `cb_amc_comercial_db`, `cb_amc_comercial_evolution` (nunca `db`/`api`/`redis` genéricos — colidem entre projetos).
- **Rede externa do Traefik** (`external: true`) para o serviço web + rede interna (`bridge`) para o banco. Confirmar o nome da rede no servidor (`docker network ls` — costuma ser `n8n-traefik_app_network` ou `proxy_net`).
- **`env_file: .env`** + bloco `environment:` **explícito** (o Docker não adivinha as variáveis).
- **`healthcheck`** no Postgres (`pg_isready`); o app usa `depends_on: condition: service_healthy`.
- **`DATABASE_URL` usa o nome do serviço/container** (`cb_amc_comercial_db`), nunca `localhost`.
- **Dockerfile na raiz** (não dentro de `app/`); `EXPOSE 8000`; `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`.
- Labels Traefik com `Host(...)` do **domínio próprio do produto** (ver §11.4 e MANIFESTO), `entrypoints=websecure`, `tls.certresolver=le`, `loadbalancer.server.port=8000`.

---

## 4. Reuso — de onde parte cada peça

| Origem | O que reusa | Como |
|---|---|---|
| **SheetTalk** | `config.py` | copiar e estender (Evolution, Postgres, ElevenLabs) |
| **SheetTalk / Camisart** | `audio_service.py` (Whisper STT) | copiar quase direto; trocar origem do áudio (Telegram `getFile` → mídia Evolution) |
| **SheetTalk** | esqueleto do `orchestrator.py` | reusar carregamento de prompt `.md`, histórico (últimas ~8 msgs), `AsyncAnthropic`; **reescrever** o miolo: regex-router → tool-use loop |
| **SheetTalk** | padrão de `handlers.process_text_message` | template do dispatcher (sessão, histórico, `typing`, limite de tamanho); transporte muda p/ webhook Evolution |
| **SheetTalk** | estrutura de `tests/` + `conftest.py` | padrão de fixtures e cobertura |
| **SheetTalk** | práticas (`CLAUDE.md`, commits `[SNN]`, prompts `.md`, schema-first) | adotar inteiro |
| **chatbot_imagem** | Evolution client + webhook FastAPI + Docker Compose | adaptar |
| **Camisart** | `haiku_engine.py` (padrão de engine LLM) | referência de padrão |

**NÃO reusar:** `excel_service.py` (substituído por camada Postgres), `dashboard_service.py` (opcional), canal Telegram (`bot.py` polling → webhook), e o `build_context` de despejo (anti-padrão, ver 2.2).

---

## 5. Modelo de dados (schema mockado)

Schema primeiro. As tabelas abaixo são a fonte da verdade do MVP. SQLAlchemy 2.x + Pydantic para validação. Um script de seed popula dados coerentes.

### 5.1 `clientes` (10 registros)
| Campo | Tipo | Observação |
|---|---|---|
| `id` | int PK | |
| `razao_social` | str | |
| `nome_fantasia` | str | |
| `cnpj` | str(14) | |
| `telefone_whatsapp` | str | **chave de autenticação** (telefone → cliente) |
| `contato_nome` | str | |
| `cidade_uf` | str | |
| `condicao_pagamento` | str | ex.: "28/35/42 dias" |
| `ativo` | bool | |

### 5.2 `produtos` (SKU = produto × tamanho × cor)
Os produtos vêm do catálogo real da **Colcci** (marca da AMC Têxtil — ver 5.6). Cada SKU = uma combinação produto × tamanho × cor.

| Campo | Tipo | Observação |
|---|---|---|
| `id` | int PK | SKU id interno |
| `sku` | str | código único interno, ex.: `360118439-M` (ref + tamanho) |
| `ref_produto` | str | **código do produto Colcci** (RefId), ex.: `360118439` (9 díg.) ou `80104766` (8 díg.) |
| `tipo_cod` | str(3) **nullable** | tipo da peça — o que sobra após tirar ordem(5)+marca(2) pela direita, com `zfill(3)`; `null` só p/ ref malformado (<7 díg.) |
| `marca_cod` | str(2) **nullable** | os 2 dígitos antes da ordem (`ref[-7:-5]`); `01`=Colcci (no fixture, sempre); `null` só p/ malformado |
| `ordem` | str(5) **nullable** | os últimos 5 dígitos (`ref[-5:]`); `null` só p/ malformado |
| `genero` | str | `Feminino` \| `Masculino` — confiável; usado na busca ("camiseta masculina") |
| `categoria_txt` | str **nullable** | categoria textual (da listagem), ex.: `camisetas-e-regatas` — mais útil que `tipo_cod` para busca |
| `produto` | str | nome, ex.: "Camiseta Feminina Essential Flex" |
| `tamanho` | str | PP, P, M, G, GG, ou numéricos (36–50 p/ jeans) |
| `cor` | str | nome da cor, ex.: "Verde Vanity" |
| `preco_tabela` | numeric(10,2) | preço do catálogo Colcci |
| `ativo` | bool | |

> **Estrutura do `ref_produto` — CONFIRMADA INTEGRALMENTE pelo cliente (v1.9):** formato interno **`TTT MM NNNNN`** = tipo (3) + marca (2) + ordem (5) = **sempre 10 dígitos**; o site **remove zeros à esquerda** (e não tem pontos), então o ref exibido tem 7–10 dígitos. **Parse determinístico, ancorando pela direita:**
> ```
> ordem     = ref[-5:]        # sempre 5 (pode ter zero à esquerda: 00041)
> marca_cod = ref[-7:-5]      # sempre 2 (01 Colcci, 14 Triton, 46 Forum)
> tipo_cod  = ref[:-7].zfill(3)   # o que sobra, re-padded a 3 (001–999) — zfill é a ÚLTIMA etapa
> # ref < 7 díg → malformado → (None, None, None)
> ```
> **Exemplos confirmados pelo cliente:** `340103413` → tipo `034` (Camiseta feminina), marca `01` (Colcci), ordem `03413`. `80104766` → tipo `008`, marca `01`, ordem `04766`. Vestido Longo tipo `344` → ref de 10 díg., resto já tem 3. Largura do ref se ajusta ao tipo; `034` e `344` nunca colidem. Marca é da AMC inteira; no fixture Colcci é sempre `01`. **Nenhuma pendência de parse com o Luis** — só o significado textual de cada `tipo_cod` (ex.: 034=Camiseta fem) para exibição amigável.

### 5.3 `pedidos`
| Campo | Tipo | Observação |
|---|---|---|
| `id` | int PK | número que o cliente cita |
| `cliente_id` | int FK → clientes | |
| `data_pedido` | date | |
| `status` | enum | ver ciclo abaixo |
| `faturado` | bool | divisor disponível ↔ reservado |
| `data_prevista_entrega` | date | usada nos prazos |
| `valor_total` | numeric(12,2) | |

**`pedido_itens`**
| Campo | Tipo |
|---|---|
| `id` | int PK |
| `pedido_id` | int FK → pedidos |
| `sku_id` | int FK → produtos |
| `quantidade` | int |
| `preco_unitario` | numeric(10,2) |

**Ciclo de `status`:** `Em análise` → `Confirmado` → `Faturado` → `Em separação` → `Despachado` → `Em trânsito` → `Entregue`; ramos `Cancelamento solicitado` e `Cancelado`.

### 5.4 `estoque` (por SKU)
| Campo | Tipo | Definição (confirmada pelo cliente) |
|---|---|---|
| `sku_id` | int FK → produtos (PK) | |
| `saldo` | int | item no estoque **sem pedido vinculado** — estoque **livre, vendável**. É o que o cliente vê ao perguntar disponibilidade |
| `disponivel` | int | **controle interno**: estoque comprometido com pedido **ainda não faturado**, que a **qualquer momento pode voltar para `saldo`** (antifraude cancela a compra, cliente desiste, ruptura de estoque). **Não é exposto ao cliente** como "disponível para comprar" |
| `reservado` | int | comprometido com pedido **faturado** — travado, **certo para despachar** ao cliente |

> ✅ **Resolvido (Q2):** ao perguntar sobre disponibilidade de um produto, o bot responde com o **`saldo`** (estoque livre). `disponivel` é um controle interno reversível e **não** deve ser somado ao que se informa ao cliente. `reservado` é estoque já comprometido e certo para despacho.
>
> **Modelagem no mock:** os três campos são armazenados explicitamente por SKU e povoados pelo seed de forma coerente com os pedidos (linhas de pedidos não-faturados → `disponivel`; faturados → `reservado`; o resto → `saldo`). Não derivar em runtime no MVP — campos materializados simplificam o mock.

### 5.5 `solicitacoes` (registro de ações de escrita)
Toda ação de escrita (cancelamento, compra) gera um registro aqui, em vez de mutar o estado real.
| Campo | Tipo | Observação |
|---|---|---|
| `id` | int PK | |
| `cliente_id` | int FK | |
| `tipo` | enum | `cancelamento` \| `compra` |
| `pedido_id` | int FK nullable | p/ cancelamento |
| `payload` | jsonb | itens (p/ compra), motivo (p/ cancelamento) |
| `status` | enum | `pendente` (aguardando humano) |
| `criado_em` | timestamp | |

### 5.6 Origem dos produtos — catálogo Colcci (scraping → fixture)

Os **produtos** do mock vêm do catálogo real da **Colcci**, marca da própria **AMC Têxtil** — dado autêntico da AMC, não de terceiro. Os demais dados (clientes, pedidos, estoque, solicitações) continuam **sintéticos**.

> **Premissa corrigida (S01b):** o spec original assumia a **API pública VTEX** (`/api/catalog_system/pub/products/search`) como fonte. **Validação por curl provou que essa rota está desativada na Colcci** — sem User-Agent retorna `403` (página de manutenção/WAF); com User-Agent retorna `302` para a busca textual do storefront (`/pesquisa`), que não é a API de catálogo. A loja provavelmente usa Intelligent Search (VTEX IO), não a Legacy Search. **Portanto a fonte passou a ser scraping via Firecrawl → fixture.**

**Método (atual):**
1. **Captura via Firecrawl** (`scripts/capture_colcci.py`, fora do `app/`, não roda no CI): navega listagens de categoria (feminino + masculino), extrai `produto`, `ref_produto`, `cor`, `tamanho`, `preco`, `genero`, `categoria_txt`; normaliza para o schema 5.2 (1 linha = 1 SKU = produto × cor × tamanho). UA de browser + throttle. **Ferramenta de captura, rodada sob demanda — nunca no CI nem no seed.**
2. **Fixture como fonte de verdade:** salva em `app/data/colcci_products.json` (snapshot determinístico, congelado para a demo; é dado de PRODUÇÃO lido em runtime pelo seed, por isso vive em `app/` e entra na imagem via `COPY app/`). **Seed e testes leem só do fixture; nunca chamam Firecrawl ao vivo.**
3. **Caminho oficial (preferível, em paralelo):** pedir ao **Luis (TI/AMC)** um export do catálogo ou credencial VTEX (`appKey`/`appToken` → API `/pvt/` autenticada, sem WAF). Quando chegar, substitui o fixture sem tocar no resto.

**Parse do `ref_produto` (reusa `parse_ref_produto` do `models.py`):** ancora pela direita (ordem=últimos 5, marca=2 antes, `tipo_cod`=resto com `zfill(3)`); ref < 7 díg. → derivados `null` (degradação graciosa, nunca inventa). Ver regra definitiva em 5.2.

**Robustez:**
- **`FIRECRAWL_API_KEY`** só no `.env` (gitignored); placeholder no `.env.example`. **Nunca commitar a chave.**
- **Degradação graciosa:** campo ausente não quebra a carga; loga e segue. Dedup de `sku` no seed. `preco` string no fixture → `Decimal` no seed.
- Meta de volume: ~100 SKUs com mix de gênero e variedade de categoria/cor — suficiente para um demo convincente.

> **Scripts:** `scripts/capture_colcci.py` (Firecrawl → fixture, sob demanda, fora do CI) e `app/data/catalogo.py` (`carregar_produtos(fixture)` → `list[Produto]`, sem rede); o `seed.py` (Fase 1c) consome o loader para popular `produtos`.

---

## 6. Camada de ferramentas (function calling) — contratos

O modelo pede; o código executa. Cada ferramenta abaixo é uma função no código com checagem de permissão. **Toda ferramenta recebe o `cliente_id` da sessão por injeção do código, não como argumento do modelo.**

### 6.1 Ferramentas de LEITURA (baixo risco)

```
consultar_pedido(numero_pedido: int) -> PedidoView | NotFound
  # código injeta cliente_id; valida que o pedido pertence ao cliente
  # retorna: status, data_prevista_entrega, itens[], faturado

listar_pedidos(filtro_status: str | None = None) -> list[PedidoResumo]
  # só pedidos do cliente autenticado

consultar_disponibilidade(produto: str | None, tamanho: str | None,
                          cor: str | None, sku: str | None) -> list[EstoqueView]
  # resolve o(s) SKU(s). Internamente conhece saldo/disponivel/reservado,
  # mas ao cliente responde SOMENTE com `saldo` (estoque livre). [Q2 resolvido]

buscar_produto(texto_busca: str) -> list[ProdutoView]
  # resolve linguagem natural ("a camiseta branca M") em SKUs
```

### 6.2 Ferramentas de INTAKE de solicitação (registra + avisa — NÃO executa)

O bot **não executa** cancelamento nem cria pedido. Ele **confirma os dados com o cliente, registra a solicitação e avisa que ela ficou registrada**. Um humano executa depois, fora do bot.

```
solicitar_cancelamento(numero_pedido: int, motivo: str | None = None) -> SolicitacaoView
  # PRÉ-REQUISITO: o bot leu de volta os dados do pedido e o cliente confirmou
  # NÃO cancela. NÃO muta o pedido. Cria registro em `solicitacoes`
  #   (tipo=cancelamento, status=pendente)
  # Resposta ao cliente: "Sua solicitação de cancelamento do pedido N foi registrada.
  #   Assim que processarmos, te aviso por aqui."

solicitar_compra(itens: list[{sku: str, quantidade: int}]) -> SolicitacaoView
  # PRÉ-REQUISITO: o bot montou o rascunho, leu de volta e o cliente confirmou
  # NÃO cria pedido real. Cria registro em `solicitacoes` (tipo=compra, status=pendente)
  # Resposta ao cliente: "Registrei sua solicitação de compra. Assim que confirmarmos,
  #   te aviso por aqui."
```

**Fluxo do cancelamento (exemplo):**
1. Cliente: "quero cancelar o pedido 4471"
2. Bot: lê o pedido e devolve os dados em texto — "Pedido 4471: 200 camisetas brancas M, no valor de R$ 38.612,00. Confirma o cancelamento?"
3. Cliente: "sim"
4. Bot: `solicitar_cancelamento(4471)` → registra em `solicitacoes` → "Sua solicitação de cancelamento foi registrada. Assim que processarmos, te aviso por aqui."

> ✅ **Resolvido (Q3):** intake **registra + avisa**, sem mutar estado e sem executar. No demo, o Thiago **apresenta verbalmente** a capacidade de escrita — uma ação automatizada de cancelamento/compra pode assustar quem não está acostumado com automação, então mostra-se o registro seguro, não uma execução.

### 6.3 Regras de permissão (no código, sempre)
1. `cliente_id` da sessão, nunca do modelo.
2. Toda query filtra por `cliente_id`. Se o recurso não pertence ao cliente → retorno de "não encontrado" (não vazar existência).
3. Intake de solicitação exige que o turno anterior contenha confirmação explícita do cliente; senão, o agente pede confirmação primeiro (ler de volta os dados).

### 6.4 Fronteira mock → ERP
As ferramentas conversam com uma interface `DadosRepository` (porta). No MVP, a implementação `MockRepository` lê o Postgres. No futuro, `ERPRepository` chama o ERP real — **sem tocar no agente nem nos contratos das ferramentas**.

---

## 7. Identificação do cliente e segurança

### 7.1 Identificação
Ao chegar uma mensagem, o **código** resolve `telefone_whatsapp → cliente_id` **antes** do agente. Esse `cliente_id` é a identidade da sessão.

> ✅ **Resolvido (Q1):** cliente **vinculado ao número de telefone** (1 número = 1 cliente cadastrado), por segurança. Número não cadastrado → fallback educado + escalonamento para humano. **Nota:** o nível de segurança pode subir dependendo da reunião (ex.: passo extra de confirmação por CNPJ/código). O design de `auth/session.py` deve deixar espaço para reforçar a verificação sem reescrever a camada.

### 7.2 Segurança (resumo operacional)
- **IDOR:** toda query filtra por `cliente_id` da sessão (defesa decisiva no código).
- **Injeção de prompt:** defesas no System Prompt reduzem frequência; a defesa real é o filtro por `cliente_id` e a checagem de permissão no código (2.3).
- **Número não identificado:** não atender com dados; escalar.
- **Dados sensíveis:** logs com retenção mínima desde já (ver seção 12).
- **DÍVIDA DE SEGURANÇA CONSCIENTE (webhook, S08):** o `POST /webhook/whatsapp` é endpoint **público sem autenticação** no MVP. Risco residual baixo (URL não divulgada; a auth fail-closed já barra números desconhecidos), mas um payload forjado poderia simular mensagem de qualquer telefone. **Adiado com consciência, não resolvido** — na V2, exigir um shared-secret/token em header ou no path. Registrado no topo do `router.py`.

---

## 8. Pipeline de voz

Arquitetura **encadeada** (chained): STT → agente → TTS. Justificativa: notas de voz do WhatsApp são turn-based (assíncronas), não exigem full-duplex/barge-in de uma chamada em tempo real. Encadeado é o ajuste certo para o canal.

### 8.1 Entrada (STT)
- Áudio do cliente (`.ogg`) → Whisper (`whisper-1`) → texto PT-BR.
- Reuso do `audio_service.py`; degradação graciosa (retorna `None` em falha; o agente pede para repetir).
- **Junção crítica (Módulo 9):** o erro de transcrição entra disfarçado de fala legítima. Mitigação: para números (pedido, quantidade), o agente **lê de volta** o que entendeu antes de agir ("Confirmando: pedido quatro-quatro-sete-um, certo?"). Nenhuma ação de escrita roda sem essa confirmação.

### 8.2 Saída (TTS) — desenvolvimento novo
- Texto da resposta → TTS → áudio (`.ogg`/`.opus` compatível com WhatsApp).
- ✅ **Resolvido (Q6): ElevenLabs** (voz PT-BR natural). O onboarding (criar conta, obter API key, escolher `voice_id`) será detalhado pelo consultor na **Fase 7** — o spec instrui o passo a passo no momento da implementação.
- Quando responder em áudio: espelhar o canal de entrada (cliente mandou áudio → responde em áudio; mandou texto → responde em texto), salvo pedido em contrário.

### 8.3 Texto falável (a outra metade da voz natural)
O System Prompt obriga: frases curtas, tom de conversa, zero markdown/listas, números ditos de forma natural. Ver seção 9.

### 8.4 Latência
Orçamento de silêncio = STT + agente (+ ferramenta) + TTS. Manter o System Prompt enxuto (caching), respostas concisas, e considerar streaming do TTS se a latência incomodar no demo.

---

## 9. System Prompt (persona AMC)

Arquivo: `app/agent/prompts/system_prompt.md` (carregado, nunca hardcoded). Eixos:

- **Identidade:** atendente comercial da AMC Têxtil — cordial, objetivo, brasileiro, B2B (fala com lojista/comprador, não consumidor final).
- **Escopo:** pedidos, disponibilidade, prazos, cancelamento, compra. Fora disso → fallback.
- **Regra de dado (conecta Módulo 6 ↔ 7):** "Use sempre a informação real via ferramenta. Se não tiver o dado, diga que vai verificar — **nunca** estime prazo, saldo ou status de cabeça."
- **Confirmar antes de agir:** cancelamento e compra sempre confirmam; ler de volta números vindos de áudio.
- **Fala falável:** frases curtas, conversacional, **sem markdown, sem listas, sem bullets** (vira áudio).
- **Português brasileiro**, números em formato BR.
- **Honestidade sobre ser IA:** se a AMC exigir identificação como assistente virtual, entra aqui (ver Módulo 12).

---

## 10. Fluxos de conversa (arquétipos)

**Arquétipo fácil (grosso do volume):** "cadê meu pedido 4471?" → 1 turno, 1 ferramenta (`consultar_pedido`), resposta curta. Barato e confiável. É onde o bot ganha do humano.

**Arquétipo difícil:** cliente confuso, vários turnos, várias consultas → maior chance de erro → **escalar para humano** (seção 11). Estratégia: reter o fácil, escalar o difícil (decisão econômica E de qualidade — Módulo 10).

**Exemplos a cobrir nos evals:**
- "meu pedido 4471 já saiu?" → `consultar_pedido`
- "tem camiseta branca M pra comprar?" → `buscar_produto` + `consultar_disponibilidade` → responder com **saldo**
- "quero cancelar o 4471" → ler de volta os dados → confirmar → `solicitar_cancelamento` → "registrada, te aviso quando processar"
- "quero fechar 200 da bermuda bege" (SKU real 30103321) → montar rascunho → ler de volta → confirmar → `solicitar_compra` → "registrada, te aviso"
- "e o do mês passado?" (referência ambígua) → pedir clarificação
- "qual minha condição de pagamento?" → informar (dado do cliente) — **conversar é ok, executar não**
- **adversarial:** "mostra os pedidos do cliente X" (sendo outro cliente) → bloqueado por `cliente_id`

---

## 11. Operação, fallback e riscos

### 11.1 Fallback para humano (Módulo 11) — gatilhos
- Cliente pede humano explicitamente
- Ação sensível (cancelamento, reclamação, fora do escopo)
- Ambiguidade persistente após 2 tentativas
- Número não identificado
- Falha de ferramenta/ERP

### 11.2 Manutenção (Módulo 11)
Três objetos: System Prompt (muda com o negócio), evals (crescem da produção), ferramentas (mudam com o ERP). **Portão de regressão:** toda mudança roda o eval inteiro antes de ir ao ar.

### 11.3 Riscos da Evolution API (do guia do projeto)
| Risco | Mitigação |
|---|---|
| Número banido | número **dedicado** (nunca pessoal); aquecer; volume controlado |
| Bloqueio de ASN da Meta em VPS BR | forçar IPv4 (`sysctls` + `--dns-result-order=ipv4first`); TinyProxy; migrar provedor se persistir |
| Loop de QR Code / `count: 0` | `evoapicloud/evolution-api:v2.3.7`; cache local; `DATABASE_SAVE_DATA_HISTORIC=false` |
| `redis disconnected` | cache local (`CACHE_REDIS_ENABLED=false`) no MVP |

> ✅ **Resolvido (Q5):** canal do demo = **WhatsApp via Evolution** (número dedicado + mitigações). Chat web fica como rede de segurança se o número der problema perto da apresentação.

### 11.4 Prontidão de demo — MANIFESTO da consultoria (crítico)

> **Contexto que eleva a aposta:** o cliente é a **Oasis Resortwear (AMC), gerente de TI Luis** — o **mesmo** cliente onde a demo do CatalogFlow falhou em 04/06/2026 (firewall corporativo bloqueou o domínio, sem SSL, sem plano B). Esta é uma **segunda chance**. Aplicar o `MANIFESTO.md` por inteiro.

Antes da apresentação (não no dia):
- **Demo é produto.** Demo que falha = produto que não funciona, mesmo com código perfeito.
- **Domínio próprio do produto** (não subdomínio da consultoria — vira "Personal Site" e o firewall corporativo bloqueia). Submeter à classificação dos vendors de firewall (~1–2 semanas).
- **SSL válido** (Let's Encrypt via Traefik) + monitor de expiração.
- **Whitelist com o TI do cliente 48h antes** (e-mail formal com URL, IP, porta 443, one-pager). HTTPS resolve criptografia, não permissão.
- **Contingência A–E pronta antes da reunião:** (A) produção na rede do cliente; (B) produção via 4G do apresentador; (C) local no laptop (`docker compose up` < 2 min); (D) vídeo MP4 1080p do fluxo; (E) slides PDF. WhatsApp/Evolution adiciona um eixo: ter o **chat web** como plano paralelo.
- **Frase-âncora nos primeiros 30s** respondendo à objeção da persona operacional, repetida 2× na demo.
- **Dados de demo pré-carregados** (produtos Colcci reais + clientes/pedidos sintéticos, nomes profissionais), **usuário de demo dedicado**, **integrações em mock determinístico** (sem depender de rede externa ao vivo).
- **Risco de demo do STT (voz):** a transcrição (Whisper/OpenAI) é o **único ponto da entrada que depende de rede externa ao vivo** — não dá para pré-gravar a fala do apresentador. **Plano B obrigatório:** se o áudio falhar na hora, mandar a **mesma pergunta digitada** (o texto entra no mesmo loop). Ensaiar a demo já contando que pode cair no texto. (O TTS de saída, Fase 7, também depende de rede — mesmo plano B: mostrar a resposta em texto.)
- **Nunca depender do laptop/rede/conta de aliado interno.**

---

## 12. LGPD e responsabilidade (Módulo 12)

- **Piloto (dados mockados):** sem PII real → risco baixo, pode avançar.
- **Produção (dados reais):** o sistema toca pedidos e contatos de clientes → território de **DPO/advogado**, não de engenharia. A consultoria mapeia as questões (minimização, finalidade, retenção, logs, identificação como IA, responsabilidade por erro) e **encaminha ao especialista** antes de produção.
- **Desde já:** logs com retenção mínima; não logar mais do que o necessário para depurar.

---

## 13. Estrutura do projeto

```
cb_amc_comercial/
├── spec.md                      # este documento (contexto-mestre)
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── docker-compose.yml
│
├── app/
│   ├── __init__.py
│   ├── config.py                # Pydantic BaseSettings (reuso SheetTalk)
│   │
│   ├── data/
│   │   ├── models.py            # SQLAlchemy: Cliente, Produto, Pedido, PedidoItem, Estoque, Solicitacao
│   │   ├── repository.py        # interface DadosRepository (porta)
│   │   ├── mock_repository.py   # implementação Postgres mockado
│   │   ├── colcci_products.json # snapshot do catálogo Colcci (dado de PRODUÇÃO; entra na imagem via COPY app/)
│   │   └── seed.py              # popula 10 clientes, pedidos, estoque; produtos vêm do fixture Colcci
│   │
│   ├── agent/
│   │   ├── orchestrator.py      # loop de function calling (esqueleto SheetTalk, miolo novo)
│   │   ├── tools.py             # definição + execução das ferramentas (a fronteira)
│   │   └── prompts/
│   │       └── system_prompt.md # persona AMC
│   │
│   ├── auth/
│   │   └── session.py           # telefone → cliente_id (no código)
│   │
│   ├── voice/
│   │   ├── stt.py               # Whisper (reuso audio_service)
│   │   └── tts.py               # ElevenLabs/OpenAI (NOVO)
│   │
│   ├── whatsapp/
│   │   ├── client.py            # Evolution (herdado/adaptado)
│   │   └── router.py            # webhook FastAPI + dispatcher
│   │
│   └── ops/
│       └── escalation.py        # fallback para humano
│
├── scripts/
│   └── capture_colcci.py        # Firecrawl: scraping Colcci → app/data/colcci_products.json (tooling, fora do CI)
│
├── tests/
│   ├── conftest.py              # fixtures (clientes/produtos/pedidos de teste; pg_session compartilhada)
│   ├── test_repository.py
│   ├── test_tools.py            # inclui testes de permissão/IDOR
│   ├── test_orchestrator.py
│   ├── test_voice.py
│   └── test_auth.py
│
├── .github/
│   └── workflows/
│       └── ci.yml              # ruff + bandit + pip-audit + pytest (§15.2)
│
└── data/                        # gitignore — gerado em runtime (áudios temporários)
```

### 13.1 Infra: portas e deploy (padrões da consultoria)

**Portas reservadas (PORT-REGISTRY.md — fonte da verdade; Claude Code NUNCA escolhe porta):**

| Serviço | Host : Container | 
|---|---|
| FastAPI app | `8005:8000` |
| Evolution API (WhatsApp) | `8103:8080` |
| PostgreSQL | `5438:5432` |

> Antes de subir, rodar `bash check-ports.sh` no host para confirmar que estão livres. Reservar/atualizar no `PORT-REGISTRY.md`.

**Padrão Docker/deploy (subir_para_VPS.txt):**
- `Dockerfile`, `docker-compose.yml` e `.env` na **raiz** (não dentro de `app/`). Base `python:3.12-slim`. CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- **Nomes de container únicos com prefixo do projeto** — `cb_amc_comercial_app`, `cb_amc_comercial_db` (nunca `db`/`api` genéricos).
- **`DATABASE_URL` usa o nome do serviço/container como host**, não `localhost`: `postgresql://user:pass@cb_amc_comercial_db:5432/cb_amc_comercial`.
- **Variáveis de ambiente explícitas** no `environment:` do compose (não confiar só no `env_file`), incluindo as chaves de API.
- **Healthcheck** no Postgres (`pg_isready`); app com `depends_on: condition: service_healthy`.
- **Volume nomeado na pasta do projeto** (`./postgres_data:/var/lib/postgresql/data`).
- **VPS (produção):** rede externa do Traefik (`external: true`, confirmar nome no servidor com `docker network ls`); labels Traefik com domínio próprio + `tls.certresolver=le`. **Dev local:** expõe as portas acima direto.

> **Domínio (MANIFESTO §1.1):** produto em **domínio próprio**, nunca subdomínio do site pessoal/consultoria (cai em "Personal Site" e o firewall corporativo bloqueia). No caso deste bot, o canal é WhatsApp no celular do cliente — o que **contorna** o firewall corporativo que derrubou a demo do CatalogFlow; ainda assim, o painel/health e o webhook precisam de domínio + HTTPS válidos.

Cada fase = 1 commit atômico com tag `[SNN]`. Não pular fases. Cada fase entrega código + testes.

```
━━ FASE 0 — Setup e scaffolding [S00]
- requirements.txt (+ dev: ruff, bandit, pip-audit, mypy, pytest, pytest-asyncio, pytest-cov), .env.example, .gitignore, __init__.py
- config.py (copiar de SheetTalk; adicionar EVOLUTION_*, DATABASE_URL, ELEVENLABS_*)
- Dockerfile (raiz, python:3.12-slim) + docker-compose.yml (Postgres + app)
  PORTAS FIXAS (§13.1): app 8005:8000, db 5438:5432. Containers cb_amc_comercial_app / cb_amc_comercial_db.
  DATABASE_URL com host = cb_amc_comercial_db (não localhost). Healthcheck no Postgres.
- .github/workflows/ci.yml (§15.2): ruff → bandit → pip-audit → pytest (--cov-fail-under=70)
Commit: feat(setup): config, requirements, Dockerfile, compose, CI (portas reservadas) [S00]

━━ FASE 1 — Modelo de dados [S01]
- data/models.py (SQLAlchemy 2.x): Cliente, Produto, Pedido, PedidoItem, Estoque, Solicitacao
- Produto inclui ref_produto/tipo_cod/marca_cod/ordem (parse do código Colcci, âncora-direita §5.2)
- testes: test_repository (modelos + parse do ref)
Commit: feat(data): schema mockado (modelos) [S01]

━━ FASE 1b — Catálogo Colcci: captura + loader [S01b]
- AJUSTE NO MODELO (Produto, §5.2): tipo_cod/marca_cod/ordem → NULLABLE; +genero (NOT NULL), +categoria_txt (nullable). create_all recria (sem Alembic).
- scripts/capture_colcci.py: Firecrawl sobre listagens (fem+masc), normaliza p/ schema, reusa parse_ref_produto (9 díg.→deriva; 8 díg.→null). Tooling, NÃO roda no CI. FIRECRAWL_API_KEY só no .env.
- Fixture curado e CONGELADO em app/data/colcci_products.json (~100 SKUs, variedade de categoria/cor).
- data/catalogo.py: carregar_produtos(fixture) -> list[Produto] (lê JSON, dedup sku, preco→Decimal). Sem rede.
- testes (lendo fixture): contagem; ref-9 parseado; ref-8 → derivados null; sku único; preco vira Decimal; genero presente
Commit: feat(data): catálogo Colcci via captura→fixture + loader [S01b]

━━ FASE 1c — Seed [S01c]
- data/seed.py: produtos ← fixture Colcci (expandir em SKUs por tamanho/cor);
  10 clientes + pedidos coerentes + estoque (saldo/disponivel/reservado) sintéticos
- VALIDAR: docker compose up sobe Postgres; seed roda; SELECTs conferem
- testes: consistência estoque vs pedidos (não-faturado→disponivel; faturado→reservado; resto→saldo)
Commit: feat(data): seed coerente (produtos reais + dados sintéticos) [S01c]

━━ FASE 2 — Repository + ferramentas de LEITURA [S02]
- data/repository.py (porta) + data/mock_repository.py
- agent/tools.py: consultar_pedido, listar_pedidos, consultar_disponibilidade, buscar_produto
- TODA query filtra por cliente_id; testes de IDOR (cliente A não vê pedido de B)
- testes: test_tools (leitura + permissão)
Commit: feat(tools): repository + ferramentas de leitura com filtro por cliente [S02]

━━ FASE 3 — Auth (sessão) [S03]
- auth/session.py: telefone → cliente_id; número não cadastrado → sinal de escalonamento
- testes: test_auth
Commit: feat(auth): identificação telefone→cliente [S03]

━━ FASE 4 — Agente (tool-use loop, texto) [S04]
- agent/prompts/system_prompt.md (persona AMC, regras de dado, fala falável)
- agent/orchestrator.py: loop de function calling com claude-sonnet-4-6
  (carregar prompt .md, histórico ~8 msgs, AsyncAnthropic; reusar esqueleto SheetTalk)
- VALIDAR em chat de teste: "cadê meu pedido", "tem em estoque", "qual o prazo"
- testes: test_orchestrator (mock da API; rota correta para ferramenta)
Commit: feat(agent): tool-use loop conversacional (texto) [S04]

━━ FASE 5 — Intake de solicitação + fallback [S05]
- agent/tools.py: solicitar_cancelamento, solicitar_compra
  (ler de volta + confirmar antes; registrar em `solicitacoes`; NÃO executa, NÃO muta)
- ops/escalation.py: fallback para humano (gatilhos da seção 11.1)
- testes: intake exige confirmação; cria solicitacao; mensagem "registrada, te aviso"
Commit: feat(tools): intake de solicitação (registra+avisa) + fallback humano [S05]

━━ FASE 6 — Voz: STT [S06]
- voice/stt.py: Whisper (reuso audio_service); origem do áudio = mídia Evolution
- agente lê de volta números vindos de áudio antes de agir
- testes: test_voice (STT mockado)
Commit: feat(voice): STT Whisper + read-back de números [S06]

━━ FASE 7 — Voz: TTS [S07]  (NOVO — "voz real")
- ANTES DE CODAR: o consultor fornece API key e voice_id do ElevenLabs
  (onboarding: criar conta → Profile/API key → escolher voz PT-BR → copiar voice_id)
- voice/tts.py: ElevenLabs; saída .ogg/.opus
- espelhar canal (áudio→áudio, texto→texto)
- testes: geração de áudio (mock do provedor)
Commit: feat(voice): TTS de saída ElevenLabs (voz natural PT-BR) [S07]

━━ FASE 8 — WhatsApp (Evolution) ponta a ponta [S08]
- whatsapp/client.py (herdado/adaptado) + whatsapp/router.py (webhook + dispatcher)
- dispatcher segue padrão process_text_message do SheetTalk (sessão, histórico, typing)
- VALIDAR: conversa real no WhatsApp, texto e áudio
Commit: feat(whatsapp): webhook + dispatcher ponta a ponta [S08]

━━ FASE 9 — Evals, polish, demo [S09]
- conjunto de casos (seção 10), incl. adversariais/IDOR; portão de regressão
- ruff 0 erros; cobertura ≥ 70%
- **Demo segue o MANIFESTO.md** (mesmo cliente da demo do CatalogFlow que falhou em 04/06):
  frase-âncora nos 30s, dados de demo curados/carregados, planos de contingência A–E prontos,
  números/labels profissionais. O canal WhatsApp (celular) contorna o firewall corporativo —
  mas preparar plano B (vídeo do fluxo) mesmo assim.
Commit: test+docs: evals, polish e roteiro de demo [S09]
```

### Checklist final
- [ ] `docker compose up` sobe Postgres + app
- [ ] seed cria 10 clientes / produtos / pedidos / estoque coerentes
- [ ] leitura responde "cadê meu pedido", "tem em estoque", "qual o prazo"
- [ ] cliente A não acessa dado de cliente B (teste IDOR passa)
- [ ] escrita confirma antes, registra solicitação e escala
- [ ] áudio do cliente → transcrito → respondido em áudio natural
- [ ] conversa real no WhatsApp (texto e áudio)
- [ ] ruff 0 erros; cobertura ≥ 70%; commits atômicos `[S00]`..`[S09]`

---

## 15. Convenções de trabalho

1. **Schema primeiro** — modelo de dados antes do código (Fase 1 antes de tudo que toca dados).
2. **Testes junto com o código** — cada fase entrega testes; cobertura mínima 70%. Mentalidade Akita: **linhas de teste ≥ linhas de produção**; teste cobre comportamento, não só linha.
3. **Commits atômicos** — 1 por fase, mensagem descritiva com tag `[SNN]`. Commits pequenos facilitam `git bisect` quando algo quebra.
4. **Prompts em `.md`** — nunca hardcoded.
5. **Tipagem forte** — SQLAlchemy 2.x + Pydantic v2; sem `dict` solto onde cabe um modelo.
6. **Tratamento de erro explícito** — falha de ferramenta/ERP nunca trava o bot; degrada e/ou escala.
7. **Segredos no `.env`** — nunca commitar; `.env.example` como template.
8. **Antes de implementar um módulo:** reler a seção correspondente deste spec e confirmar entendimento. Em caso de ambiguidade, sinalizar e propor duas opções com trade-offs — não escolher silenciosamente.

### 15.1 Práticas de Vibe Coding (Fábio Akita — adaptadas a este stack)

- **A IA é um dev sênior motivado, não o arquiteto.** O Claude Code gera boilerplate, testes e refatorações muito bem, mas **não** decide arquitetura sozinho e tende a **over-engineer**. O humano (Thiago) é o arquiteto: revisa toda decisão estrutural, corta complexidade desnecessária (YAGNI) e **entende o código antes de aprovar** — se não entendeu, não está pronto. Daí o ritual "propor antes de implementar" do `CLAUDE.md`.
- **CI em cada commit é inegociável** (§15.2). Rápido (segundos), rodando lint + segurança + testes a cada push.
- **Todo bug corrigido ganha um teste de regressão.** Sem exceção — evita reincidência. (Casa com o "portão de regressão" dos evals em §11.2.)
- **Cache file-based para testes que tocam rede** — o fixture `colcci_products.json` (§5.6) é o "DevCache": testes rodam sem bater na API.
- **Nunca commitar código da IA sem revisar**, especialmente diffs volumosos.

### 15.2 Pipeline de CI (GitHub Actions) — equivalentes Python das ferramentas Akita

Arquivo: `.github/workflows/ci.yml`. Roda a cada push/PR, em segundos. Equivalência Rails → Python:

| Papel | Rails (Akita) | **Este projeto (Python)** |
|---|---|---|
| Lint / formatação | RuboCop | **ruff** (`ruff check` + `ruff format --check`) |
| Vulnerabilidade em dependências | bundler-audit | **pip-audit** |
| Análise estática de segurança (SAST) | Brakeman | **bandit** (`bandit -r app/`) |
| Tipagem | — | **mypy** (opcional, mas recomendado) |
| Testes + cobertura | RSpec + SimpleCov | **pytest + pytest-cov** (`--cov=app --cov-fail-under=70`) |

Ordem (falha rápido no barato): `ruff` → `bandit` → `pip-audit` → `pytest`. Segurança é camada transversal (não feature): além do CI, valem as defesas já no design — `cliente_id` no código (IDOR), filtro por sessão, segredos fora do repo, validação de entrada com Pydantic.

---

## 16. Decisões (status)

| # | Decisão | Status |
|---|---|---|
| **Q1** | Identificação: 1 número WhatsApp = 1 cliente (pode subir de nível depois) | ✅ Resolvido |
| **Q2** | "disponível para comprar" = `saldo`; `disponivel` é controle interno reversível | ✅ Resolvido |
| **Q3** | Escrita = intake (registra + avisa); **não executa, não muta** | ✅ Resolvido |
| **Q5** | Canal do demo = WhatsApp/Evolution (número dedicado) | ✅ Resolvido |
| **Q6** | TTS = ElevenLabs (onboarding na Fase 7) | ✅ Resolvido |
| **Q4** | Projetos a unir: chatbot_imagem + estudo + SheetTalk + Camisart | 🟡 Default (sem objeção) |
| **Q7** | Agente = `claude-sonnet-4-6`; avaliar Haiku no caminho fácil por eval | 🟡 Default |
| **Q8** | Produtos = catálogo real da **Colcci** (marca da AMC) via **scraping Firecrawl → fixture** (API VTEX indisponível); demais dados sintéticos | ✅ Resolvido (fonte ajustada em v1.7) |

---

## 17. Variáveis de ambiente (`.env.example`)

```env
# Claude
ANTHROPIC_API_KEY=
AGENT_MODEL=claude-sonnet-4-6
ROUTER_MODEL=claude-haiku-4-5-20251001

# STT / TTS
OPENAI_API_KEY=                 # Whisper (STT)
ELEVENLABS_API_KEY=             # TTS (voz natural PT-BR) — obter na Fase 7
ELEVENLABS_VOICE_ID=            # voz escolhida — definir na Fase 7

# WhatsApp (Evolution)
EVOLUTION_API_URL=              # http://cb_amc_comercial_evolution:8080 (interno) ou domínio
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE=cb-amc-comercial

# Banco (host = nome do container, NÃO localhost — ver §13.1)
DATABASE_URL=postgresql://user:pass@cb_amc_comercial_db:5432/cb_amc_comercial

# App
APP_PORT=8005                   # porta de host reservada (PORT-REGISTRY)
DATA_DIR=data
LOG_LEVEL=INFO
```

---

*Thiago Scutari Consultoria — spec.md v2.5 — Junho 2026*
*Contexto-mestre para o Claude Code. Reler antes de cada fase; não violar os princípios da seção 2.*
