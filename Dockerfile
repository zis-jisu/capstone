FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2

WORKDIR /app

COPY requirements-ml.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.5.1+cpu" \
    && pip install --no-cache-dir -r requirements-ml.txt

COPY rgae_service ./rgae_service

CMD ["sh", "-c", "exec uvicorn rgae_service.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
