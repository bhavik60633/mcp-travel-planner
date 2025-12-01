# Use official Python image
FROM python:3.11-slim

# Install system tools + Node.js + npm
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        nodejs \
        npm && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app files
COPY . .

# Streamlit settings
ENV PYTHONUNBUFFERED=1
ENV PORT=8501
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Default command: run Streamlit app
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
