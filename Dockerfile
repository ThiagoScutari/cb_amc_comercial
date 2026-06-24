# Imagem de runtime — só dependências de produção (requirements.txt).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Libs de SISTEMA do WeasyPrint (Pango/Cairo/GDK-PixBuf/ffi + fontes-base). O pip sozinho NÃO
# basta: sem estas o render do PDF quebra em runtime. --no-install-recommends + limpeza das
# listas do apt p/ manter a imagem enxuta.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências primeiro (cache de camada).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação.
COPY app/ ./app/

# Scripts operacionais (seed, cadastro de cliente-demo) — rodados via
# `docker compose exec app python -m scripts.<nome>`. Sem isto, scripts/ não
# entra na imagem. O fixture do catálogo já vai em app/data/colcci_products.json.
COPY scripts/ ./scripts/

# Não rodar como root (boa prática / bandit-friendly).
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
