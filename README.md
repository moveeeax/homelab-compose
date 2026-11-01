# homelab-compose

[![ci](https://github.com/moveeeax/homelab-compose/actions/workflows/ci.yml/badge.svg)](https://github.com/moveeeax/homelab-compose/actions/workflows/ci.yml)
![language](https://img.shields.io/badge/config-docker--compose-2496ED?logo=docker&logoColor=white)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A batteries-included, copy-and-run homelab stack: a **Traefik** reverse proxy
with automatic TLS, a full **Prometheus + Grafana** monitoring stack with
prewired dashboards, and **scheduled restic backups** — all driven by a single
`.env` file.

Edit `.env`, run `docker compose up -d`, and you have HTTPS routing, metrics,
and backups without hand-writing any of it.

## What's inside

| Service        | Image                              | Purpose                                        |
| -------------- | ---------------------------------- | ---------------------------------------------- |
| `traefik`      | `traefik:v3.7.17`                  | Reverse proxy, automatic Let's Encrypt TLS, dashboard |
| `prometheus`   | `prom/prometheus:v3.15.1`          | Metrics store, scrapes the exporters below     |
| `grafana`      | `grafana/grafana:13.3.0`           | Dashboards, provisioned datasource + panels    |
| `node-exporter`| `prom/node-exporter:v1.12.1`       | Host CPU / memory / disk metrics               |
| `cadvisor`     | `ghcr.io/google/cadvisor:v0.60.6`  | Per-container metrics                          |
| `backup`       | built from `backup/` (`restic/restic:0.19.1`) | `restic` snapshots on a cron schedule + prune  |

Images are pinned to exact versions; bump them deliberately and read the
upstream release notes first.

## How it works

The root `docker-compose.yml` defines Traefik plus two networks — a public
`web` network Traefik routes on, and an `internal` network with no host ports —
and pulls in per-service fragments with Compose's `include:`:

```yaml
include:
  - compose/monitoring.yml
  - compose/backup.yml
```

Services opt into routing with Traefik labels; the static Traefik config lives
in the compose `command:` flags so `${ACME_EMAIL}` and `${DOMAIN}` interpolate
from `.env`. TLS options and shared security headers are in
`traefik/dynamic/tls.yml` (the file provider). Grafana ships with a provisioned
Prometheus datasource and a "Homelab Overview" dashboard, so metrics show up on
first boot. The backup container runs a small cron loop that calls
`restic backup` and `restic forget --prune` on the schedule you set.

## Usage

Copy the sample env, edit domains and secrets, and bring the stack up:

```console
$ cp .env.example .env    # edit DOMAIN, ACME_EMAIL, secrets
$ docker compose up -d
[+] Running 7/7
 ✔ Network web             Created
 ✔ Container traefik       Started
 ✔ Container prometheus    Started
 ✔ Container node-exporter Started
 ✔ Container cadvisor      Started
 ✔ Container grafana       Started
 ✔ Container backup        Started
```

Then browse to `https://grafana.${DOMAIN}` (dashboards) and
`https://traefik.${DOMAIN}` (proxy dashboard, behind basic-auth).

Validate the stack without starting it — handy in CI or a pre-commit hook:

```console
$ make validate
==> docker compose config
    ok
==> pytest
12 passed in 0.20s
```

Force a backup or run a restore drill:

```console
$ make backup                 # docker compose exec backup backup.sh
$ make restore DEST=/restore  # restore the latest snapshot
```

See [`examples/`](examples/) for a minimal `.env`, an S3/MinIO backup config,
and the restore drill.

## Configuration

Everything is set through `.env` (see `.env.example` for the annotated list):

| Variable                   | What it controls                                   |
| -------------------------- | -------------------------------------------------- |
| `DOMAIN`                   | Base domain; services publish as `<svc>.${DOMAIN}` |
| `ACME_EMAIL`               | Let's Encrypt account email                         |
| `TRAEFIK_DASHBOARD_AUTH`   | `user:bcrypt` for the Traefik dashboard            |
| `GRAFANA_ADMIN_PASSWORD`   | Grafana admin password                             |
| `PROMETHEUS_RETENTION`     | Metrics retention window (e.g. `15d`)              |
| `RESTIC_REPOSITORY`        | Backup target (local path or `s3:...`)             |
| `RESTIC_PASSWORD`          | Backup encryption password                         |
| `BACKUP_SOURCE`            | Host directory backed up (read-only)               |
| `BACKUP_CRON`              | Backup schedule (crontab format)                   |
| `RESTIC_KEEP_DAILY/WEEKLY` | Retention policy for `restic forget`               |

## Upgrading an existing install

Prometheus and Grafana migrate their on-disk data when a newer major
version starts for the first time, and the older version cannot read the
migrated data after a downgrade:

- Prometheus v3 TSDB data can only be read by v2.55 or newer
  ([migration guide](https://github.com/prometheus/prometheus/blob/main/docs/migration.md#tsdb-format-and-downgrade)).
- Grafana 12 rewrites the annotation table and Grafana 13 moves dashboards
  and folders to unified storage; rolling back needs a database backup
  ([upgrade guides](https://github.com/grafana/grafana/tree/main/docs/sources/upgrade-guide)).

Before pulling new images on a running stack, stop it and copy the
`prometheus-data` and `grafana-data` volumes somewhere safe.

## Teardown

```console
$ docker compose down            # stop, keep named volumes (data survives)
$ docker compose down -v         # also delete volumes (metrics + backup cache)
```

Your restic repository lives outside the stack (`RESTIC_REPOSITORY`), so
`down -v` never touches your actual backups.

## Tests

The `tests/` suite parses every YAML/JSON file, checks that the compose files
only reference variables documented in `.env.example`, verifies the exporters
are wired to Prometheus and Grafana, and — when Docker is present — renders the
merged model with `docker compose config`. Run it with `make test`.

## License

MIT — see [LICENSE](LICENSE).
