# ADR-0003 — Relatório visual em PDF (a Cloud API oficial não aceita HTML)

- Status: Aceito
- Data: 2026-06-24
- Fase: S18 (Frentes B e C da sprint S18; teste real no WhatsApp da VPS)

## Contexto

O projeto migrou para a **WhatsApp Cloud API oficial (Meta/Graph)** — decisão de
profissionalismo e conformidade: não depender de um meio não-oficial em produção. A
**EvolutionAPI** (origem do projeto, mantida só como rollback comentado) automatiza o
WhatsApp **Web**, por isso aceitava qualquer arquivo — inclusive o HTML da cópia visual da
S16. A Cloud API **não** é o WhatsApp Web: ela tem uma **lista fechada de mimetypes** para
documento (`application/pdf`, `…wordprocessingml.document`/docx, `…spreadsheetml.sheet`/xlsx,
`…presentationml.presentation`/pptx, `text/plain`). `text/html` **não** está na lista.

No teste real na VPS, o envio do resumo visual da S16 (HTML, `text/html`) voltou **HTTP 400**
da Meta ("Param file must be one of: …pdf, …"), e o best-effort engolia a falha em silêncio: o
texto chegava, o documento não. Diagnóstico: não é limitação nossa — é a plataforma oficial.

No mesmo teste, dois problemas de áudio: a resposta em voz chegava como **arquivo para baixar**,
não como nota de voz inline (faltava o campo `voice: true` no objeto `audio`, além do formato
OGG/OPUS mono que já tínhamos).

## Decisão

1. **Relatório visual passa a ser PDF (`application/pdf`).** Reusar os templates HTML da S16
   (`gerar_html_*`, intactos) e renderizá-los para PDF com **WeasyPrint** (`html_para_pdf` em
   `app/report/pdf.py`). Os call-sites do router enviam o PDF como documento (mimetype
   `application/pdf`, filenames `pedidos.pdf`/`notas_fiscais.pdf`/`titulos.pdf`/`devolucoes.pdf`),
   mantendo o best-effort (se render ou envio falham, o texto/áudio já saiu).
2. **Áudio como nota de voz inline:** `voice: true` no objeto `audio` **junto** com OGG/OPUS
   mono (`opus_48000_64`) — os dois são necessários; só o formato não basta.
3. **WeasyPrint, não navegador headless.** O CSS dos templates é simples (tabelas + cards);
   WeasyPrint (puro-Python + libs de sistema) basta e é muito mais leve que Chromium/Playwright.

## Consequências

- **Nova dependência WeasyPrint** (`weasyprint==62.3`, com `pydyf==0.10.0` pinado — o 0.11+
  mudou `transform()` e quebra o 62.3). Exige **libs de sistema** no Dockerfile (Pango, Cairo,
  GDK-PixBuf, libffi + fonte base), ~40–80 MB na imagem — bem menos que um browser headless.
  Quem rodar **fora** do container precisa dessas libs instaladas.
- **CSS do grid trocado para `inline-block`.** WeasyPrint 62.3 não suporta
  `repeat(auto-fit, minmax(...))`; os cards do `.cards` empilhariam. A troca por `inline-block`
  é fiel no WeasyPrint **e** no navegador (mudança trivial em `_SHELL`).
- **PDF é mais fiel a "2ª via"** que um HTML que abre no navegador — combina melhor com a
  expectativa de documento comercial.
- **HTML por documento é impossível na plataforma oficial** — registrar aqui evita que o "eu
  do futuro" tente reintroduzir HTML achando que é bug nosso. Se algum dia precisar de HTML
  interativo, o caminho é outro canal (link/web), não o documento da Cloud API.
- O `enviar_documento` do client já era genérico em `mimetype`/`filename`: o conserto foi nos
  call-sites + o novo passo de render, sem mudar a mecânica de upload/mensagem de mídia.
