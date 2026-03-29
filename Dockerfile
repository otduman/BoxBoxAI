# Stage 1: Build the React frontend
FROM node:20-slim AS frontend-builder
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python backend
FROM python:3.13-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY brain/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY brain/ ./brain/
COPY driving-data/ ./driving-data/

# Copy built frontend
COPY --from=frontend-builder /web/dist ./web/dist

# Create uploads directory
RUN mkdir -p uploads

EXPOSE 8000

CMD uvicorn brain.server:app --host 0.0.0.0 --port ${PORT:-8000}
