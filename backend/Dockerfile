FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libffi-dev \
    libxml2-dev \
    libxslt-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only torch first (saves ~500MB)
RUN pip install --no-cache-dir --timeout=300 \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.3.0

# Install everything else
RUN pip install --no-cache-dir --timeout=300 -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "300", "--access-logfile", "-", "run:app"]