# Use official Python image
FROM python:3.11-slim

# Install system dependencies + Node.js (required for MCP)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        nodejs \
        npm && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Railway uses PORT env variable automatically
EXPOSE 8000

# Start FastAPI (Lovable-ready)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

