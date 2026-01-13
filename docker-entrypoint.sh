#!/bin/bash
set -e

# RSS Feed Generator - Docker Entrypoint
# Runs feed generation on startup and schedules hourly updates

FEEDS_DIR="/app/feeds"
CACHE_DIR="/app/cache"
CRON_SCHEDULE="${CRON_SCHEDULE:-0 * * * *}"  # Default: hourly

echo "=== RSS Feed Generator ==="
echo "Feed URL: ${FEED_BASE_URL}"
echo "Schedule: ${CRON_SCHEDULE}"

# Ensure directories exist
mkdir -p "$FEEDS_DIR" "$CACHE_DIR"

# Function to run feed generators
run_feeds() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running feed generators..."
    cd /app
    python feed_generators/run_all_feeds.py
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Feed generation complete."
}

# Run feeds on startup
run_feeds

# Set up cron job for scheduled updates
echo "$CRON_SCHEDULE cd /app && python feed_generators/run_all_feeds.py >> /var/log/cron.log 2>&1" > /etc/cron.d/rss-feeds
chmod 0644 /etc/cron.d/rss-feeds
crontab /etc/cron.d/rss-feeds

# Start cron in background
cron

echo "=== Starting HTTP server on port 8080 ==="
echo "Feeds available at: ${FEED_BASE_URL}"

# Serve feeds directory via Python's built-in HTTP server
cd /app
exec python -m http.server 8080 --directory .
