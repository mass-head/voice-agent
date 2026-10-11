# Stage 1: Build React Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app
COPY ada_v2-main/package*.json ./
RUN npm install
COPY ada_v2-main/ ./
RUN npm run build

# Stage 2: Python Backend Runtime
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for audio, OpenCV, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    portaudio19-dev \
    libasound2-dev \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY ada_v2-main/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend and built frontend assets
COPY ada_v2-main/ ./ada_v2-main/
COPY --from=frontend-builder /app/dist ./ada_v2-main/dist

# Default port (Render overrides via $PORT environment variable)
ENV PORT=8000
EXPOSE 8000

WORKDIR /app/ada_v2-main
CMD ["python", "backend/server.py"]
