# Imagem de runtime — só dependências de produção (requirements.txt).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Instala dependências primeiro (cache de camada).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação.
COPY app/ ./app/

# Não rodar como root (boa prática / bandit-friendly).
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
