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

## Backup monitoring

Every backup run writes its outcome to `backup.prom` on the `backup-metrics`
volume. node-exporter mounts the same volume and exports the file through its
textfile collector (`--collector.textfile.directory`), so Prometheus scrapes
it with the rest of the host metrics:

| Metric                                  | Meaning                                              |
| --------------------------------------- | ---------------------------------------------------- |
| `homelab_backup_last_success_timestamp` | Unix time of the last successful run                 |
| `homelab_backup_duration_seconds`       | Duration of that run (backup + forget + prune)       |
| `homelab_backup_bytes_added`            | Bytes it added to the repository (restic `data_added`) |
| `homelab_backup_snapshot_count`         | Snapshots tagged `homelab` after it                  |
| `homelab_backup_last_run_timestamp`     | Unix time the last run finished, success or not      |
| `homelab_backup_last_run_success`       | `1` if the last run succeeded, `0` if it failed      |
| `homelab_backup_stale_after_seconds`    | `BACKUP_STALE_AFTER_SECONDS`, used by `BackupStale`  |

A failed run only updates the `last_run_*` series; the success metrics keep
the values from the last good run. Any non-zero restic exit counts as a
failure, including exit code 3 (some source files could not be read).

The "Homelab Overview" dashboard has a backup row built on these metrics, and
`prometheus/rules/backup.yml` defines three alerts:

- `BackupStale`: the last success is older than `BACKUP_STALE_AFTER_SECONDS`
  (default 26h, sized for a daily `BACKUP_CRON`).
- `BackupFailed`: the most recent run failed.
- `BackupMetricsMissing`: node-exporter has not exported `backup.prom` for an
  hour, so the other two cannot fire.

The stack has no Alertmanager: firing alerts show on the Prometheus `/alerts`
page. To get pushed, set `BACKUP_NOTIFY_URL`. After each run the backup
container POSTs a one-line summary to it on success, and to
`BACKUP_NOTIFY_FAIL_URL` (default `${BACKUP_NOTIFY_URL}/fail`) on failure.
That matches healthchecks.io ping URLs as-is; for ntfy, set both variables to
the topic URL. A failed ping is logged and does not fail the backup.

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
20 passed in 1.20s
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
| `BACKUP_STALE_AFTER_SECONDS` | Age of the last success that fires `BackupStale` (default 26h) |
| `BACKUP_NOTIFY_URL`        | Optional ping URL after each run (healthchecks.io, ntfy) |
| `BACKUP_NOTIFY_FAIL_URL`   | Failure ping URL (default `${BACKUP_NOTIFY_URL}/fail`) |

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
`prometheus-data` and `grafana-data` volumes somewhere safe. The compose
project is named `homelab`, so `docker volume ls` shows them as
`homelab_prometheus-data` and `homelab_grafana-data`.

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
are wired to Prometheus and Grafana, runs `backup.sh` against a stub
`restic` to check the metrics file and notify pings, and — when Docker is present — renders the
merged model with `docker compose config`. Run it with `make test`.

## License

MIT — see [LICENSE](LICENSE).
