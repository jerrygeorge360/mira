FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MIRA_DB_PATH=/data/sqlite/mira.db \
    CHROMA_DB_PATH=/data/chroma

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m pip install -r requirements-dev.txt

COPY . .

RUN mkdir -p /data/sqlite /data/chroma

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
