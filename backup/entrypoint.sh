#!/usr/bin/env bash
# Initialise the restic repo (once) and install the backup cron job.
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=metrics.sh
source /usr/local/bin/metrics.sh

: "${BACKUP_CRON:=0 3 * * *}"

echo "homelab-backup: repository=${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY}"

# `restic cat config` succeeds only on an initialised repo; init if missing.
if ! restic cat config >/dev/null 2>&1; then
  echo "homelab-backup: initialising new restic repository"
  restic init
fi

# Publish the metrics file right away (keeping values from earlier runs), so
# node-exporter exports the stale threshold before the first scheduled run.
metrics_load
metrics_write

LOG=/var/log/backup.log
touch "$LOG"

# Install the schedule. Env is exported into the crontab so the job sees it.
{
  echo "RESTIC_REPOSITORY=${RESTIC_REPOSITORY}"
  echo "RESTIC_PASSWORD=${RESTIC_PASSWORD}"
  echo "RESTIC_KEEP_DAILY=${RESTIC_KEEP_DAILY:-7}"
  echo "RESTIC_KEEP_WEEKLY=${RESTIC_KEEP_WEEKLY:-4}"
  echo "AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}"
  echo "AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}"
  echo "BACKUP_METRICS_DIR=${METRICS_DIR}"
  echo "BACKUP_STALE_AFTER_SECONDS=${STALE_AFTER}"
  echo "BACKUP_NOTIFY_URL=${BACKUP_NOTIFY_URL:-}"
  echo "BACKUP_NOTIFY_FAIL_URL=${BACKUP_NOTIFY_FAIL_URL:-}"
  echo "${BACKUP_CRON} /usr/local/bin/backup.sh >> ${LOG} 2>&1"
} > /etc/crontabs/root

echo "homelab-backup: scheduled '${BACKUP_CRON}' (run 'docker compose exec backup backup.sh' for an ad-hoc run)"

# Run the cron daemon in the foreground and stream the backup log.
crond -f -l 8 &
exec tail -F "$LOG"
