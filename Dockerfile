FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1001 chatbot \
 && useradd  --system --uid 1001 --gid chatbot --home /app --shell /usr/sbin/nologin chatbot

COPY pyproject.toml ./
COPY app ./app
COPY supabase ./supabase
RUN pip install --upgrade pip && pip install . \
 && chown -R chatbot:chatbot /app

# Drop root before runtime. The container still listens on 8000 because
# we are >1024.
USER chatbot

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
