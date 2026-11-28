FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an ordinary user, not root.
RUN useradd --system --no-create-home app
USER app

EXPOSE 8000

# Migrations are NOT run here: run them once per release (see docs/DEPLOY_AWS.md),
# so that several containers starting together never migrate at the same time.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "-"]
