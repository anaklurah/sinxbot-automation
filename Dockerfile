# Use official Microsoft Playwright Python base image with browsers pre-installed
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set working directory
WORKDIR /app

# Install system dependencies (FFmpeg for video rendering, Xvfb for virtual display, fonts)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    fontconfig \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first for layer caching
COPY requirements.txt .

# Install Python packages & download Camoufox anti-detect browser binary
RUN pip install --no-cache-dir -r requirements.txt && \
    camoufox fetch

# Copy application source code
COPY . .

# Create directory structure for downloads, assets, and profiles
RUN mkdir -p downloads/raw downloads/rendered downloads/meta assets/profiles

# Expose Web Dashboard port
EXPOSE 8080

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=0 \
    OSAP_DB_PATH=/app/osap.db

# Command to launch the Web Dashboard server
CMD ["python", "manage.py", "web", "--host", "0.0.0.0", "--port", "8080"]
