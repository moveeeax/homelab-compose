#!/usr/bin/env bash
# Initialise the restic repo (once) and install the backup cron job.
set -euo pipefail

: "${BACKUP_CRON:=0 3 * * *}"

echo "homelab-backup: repository=${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY}"

# `restic cat config` succeeds only on an initialised repo; init if missing.
if ! restic cat config >/dev/null 2>&1; then
  echo "homelab-backup: initialising new restic repository"
  restic init
fi

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
  echo "${BACKUP_CRON} /usr/local/bin/backup.sh >> ${LOG} 2>&1"
} > /etc/crontabs/root

echo "homelab-backup: scheduled '${BACKUP_CRON}' (run 'docker compose exec backup backup.sh' for an ad-hoc run)"

# Run the cron daemon in the foreground and stream the backup log.
crond -f -l 8 &
exec tail -F "$LOG"
