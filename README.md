# homelab-compose

> A batteries-included homelab stack you can actually copy: reverse proxy, metrics, backups.

**Status:** 🚧 In development

## Overview

A reference docker-compose self-hosting stack: Traefik reverse proxy plus monitoring and backups.

## Features

- Traefik reverse proxy with automatic TLS and dashboard
- Monitoring: Prometheus + Grafana + node/cadvisor exporters with prewired dashboards
- Scheduled backups of volumes to a target (restic/rclone)
- `.env`-driven configuration and per-service compose fragments
- Documented bring-up and teardown

## Stack

docker-compose, Traefik, Prometheus, Grafana, restic/rclone.

## Usage

```yaml
cp .env.example .env  # edit domains/secrets
docker compose up -d
```

## License

MIT
