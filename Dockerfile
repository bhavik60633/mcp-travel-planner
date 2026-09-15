# Travel With Yori backend: the FastAPI app (Python) and the Airbnb MCP server it starts (Node).

# Node 22 installs the pinned Airbnb MCP server.
FROM node:22-bookworm-slim AS airbnb
WORKDIR /app/mcp-servers/airbnb
COPY mcp-servers/airbnb/package.json mcp-servers/airbnb/package-lock.json ./
RUN npm ci --omit=dev

# Python runs the API; the node program is copied in so the API can start the Airbnb server.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=airbnb /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=airbnb /app/mcp-servers/airbnb/node_modules mcp-servers/airbnb/node_modules

# Render sets PORT (10000); without it the app listens on 8000 as before.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
