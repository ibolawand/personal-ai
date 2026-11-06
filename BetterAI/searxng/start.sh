#!/bin/bash
# Starts the local search engine Aria uses for web results. Safe to run again.
set -e
cd "$(dirname "$0")"
mkdir -p config
if [ ! -f config/settings.yml ]; then
  # the secret only signs SearXNG's own cookies; it's created here and never committed
  cat > config/settings.yml <<YML
use_default_settings: true
server:
  secret_key: "$(openssl rand -hex 32)"
  limiter: false          # only this computer can reach it
  image_proxy: false
search:
  formats: [html, json]   # json is what Aria reads
YML
fi
docker compose up -d
echo "Waiting for SearXNG..."
for i in $(seq 1 30); do
  if curl -fs http://127.0.0.1:8888/healthz >/dev/null; then echo "SearXNG is running on http://127.0.0.1:8888"; exit 0; fi
  sleep 1
done
echo "SearXNG didn't answer yet; check: docker logs aria-searxng"
