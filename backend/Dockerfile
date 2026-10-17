FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# The PyTorch CPU index provides torch==2.3.0+cpu (no CUDA libraries)
RUN pip install --no-cache-dir --timeout=300 \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# Fetch the embedding model now so a cold start does not download it. This layer
# depends only on the script and the settings it reads, not on the app code.
COPY config/ config/
COPY scripts/download_model.py scripts/download_model.py
COPY scripts/__init__.py scripts/__init__.py
RUN python -m scripts.download_model

# The model is now in the image: never ask huggingface.co about it again.
ENV EMBEDDING_OFFLINE=true

COPY . .

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]