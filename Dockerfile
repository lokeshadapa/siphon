# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set working directory to /code instead of /app
WORKDIR /code

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first (for better Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py .
COPY batch_runner.py .
COPY scraper.py .
COPY uploader.py .

# Create directories for data (will be mounted from host)
RUN mkdir -p /code/data

# Set environment variables
ENV PYTHONPATH=/code
ENV PYTHONUNBUFFERED=1

# Make main.py executable
RUN chmod +x main.py

# Set the default command
ENTRYPOINT ["python", "main.py"]

# Health check (optional)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; print('Container is healthy')" || exit 1