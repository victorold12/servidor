FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

EXPOSE 8000
# Respeita a porta que a nuvem injeta ($PORT); cai em 8000 no local.
# Em produção use uma origem específica em ALLOWED_ORIGINS, não *
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
