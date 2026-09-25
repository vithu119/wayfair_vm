FROM python:3.11

WORKDIR /app

# bust-cache-2026-09-15b
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
