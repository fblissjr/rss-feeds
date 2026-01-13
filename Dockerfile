# RSS Feed Generator - Self-Hosted Container
# Generates RSS feeds on schedule and serves them via HTTP

FROM python:3.11-slim

# Install system dependencies for Selenium/Chrome
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    curl \
    unzip \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome for Selenium-based generators
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy requirements and install dependencies
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy application code
COPY feed_generators/ ./feed_generators/
COPY makefiles/ ./makefiles/
COPY Makefile .

# Create directories for feeds and cache
RUN mkdir -p feeds cache

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Environment variables
ENV FEED_BASE_URL=http://localhost:8080/feeds
ENV PYTHONUNBUFFERED=1
ENV CHROME_BIN=/usr/bin/google-chrome

# Expose HTTP port for serving feeds
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/feeds/ || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
