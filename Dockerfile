FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# PrusaSlicer is needed by the FastAPI backend to generate real G-code estimates.
# The fallback fonts/libs help PrusaSlicer run headlessly inside Linux.
RUN apt-get update && apt-get install -y --no-install-recommends \
    prusa-slicer \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

# Render provides PORT. Default is 10000.
ENV PORT=10000
ENV PRUSASLICER_PATH=/usr/bin/prusa-slicer

EXPOSE 10000

CMD uvicorn server:app --host 0.0.0.0 --port ${PORT}
