# Examples

## Minimal `.env`

The smallest config that brings the stack up on a real domain:

```dotenv
DOMAIN=lab.example.com
ACME_EMAIL=me@example.com
TRAEFIK_DASHBOARD_AUTH=admin:$$2y$$05$$examplebcrypthashexamplebcrypthashexample
GRAFANA_ADMIN_PASSWORD=super-secret
RESTIC_REPOSITORY=/srv/backups/restic
RESTIC_PASSWORD=another-secret
BACKUP_SOURCE=/srv/homelab/data
```

Then:

```bash
docker compose up -d
```

Traefik requests certificates on first request, so give it a minute after
DNS for `*.lab.example.com` points at the host.

## Backing up to S3 / MinIO

Set an S3-style restic repository and provide credentials:

```dotenv
RESTIC_REPOSITORY=s3:s3.eu-central-1.amazonaws.com/my-homelab-backups
RESTIC_PASSWORD=another-secret
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
BACKUP_CRON=0 */6 * * *
```

## Ad-hoc backup and restore drill

```bash
# force a backup right now
docker compose exec backup backup.sh

# restore the latest snapshot into /restore inside the container
docker compose exec backup restore.sh /restore
```

## Backup alerts to your phone

Ping a [healthchecks.io](https://healthchecks.io/) check after every run.
Failures go to the same URL with `/fail` appended, and the check also alerts
when pings stop arriving:

```dotenv
BACKUP_NOTIFY_URL=https://hc-ping.com/your-check-uuid
```

Or post to an [ntfy](https://ntfy.sh/) topic on both outcomes:

```dotenv
BACKUP_NOTIFY_URL=https://ntfy.sh/my-homelab-backups
BACKUP_NOTIFY_FAIL_URL=https://ntfy.sh/my-homelab-backups
```

With a 6-hourly `BACKUP_CRON`, tighten the stale alert to 7 hours:

```dotenv
BACKUP_STALE_AFTER_SECONDS=25200
```
