# =====================================================================
# Modular-NeuroClips Studio - Production Container
# =====================================================================
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8000 \
    DEVICE=cpu

# Install system dependencies, FFmpeg & Fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-liberation \
    curl \
    git \
    build-essential \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies (CPU-optimized PyTorch build)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Install Remotion dependencies if available
COPY remotion ./remotion
RUN cd remotion && npm install --omit=dev || true

# Copy full application codebase
COPY . .

# Create required output directories
RUN mkdir -p render_output curriculum_output exports identities

# Expose Web Portal Port
EXPOSE 8000

# Launch Studio
CMD ["uvicorn", "src.dashboard:app", "--host", "0.0.0.0", "--port", "8000"]
