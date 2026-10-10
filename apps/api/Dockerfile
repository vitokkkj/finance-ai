FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY apps/api/requirements.txt /tmp/
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1 \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --create-home app \
    && mkdir -p /home/app/.config/sophia \
    && chown -R app:app /home/app/.config

COPY apps/api /workspace/apps/api
COPY worker /workspace/worker

USER app
WORKDIR /workspace/apps/api

ENV PYTHONPATH=/workspace/apps/api:/workspace

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
