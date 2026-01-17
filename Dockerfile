FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (needed for efficient building of some python packages)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command (will be overridden in docker-compose)
CMD ["python", "api/main.py"]
