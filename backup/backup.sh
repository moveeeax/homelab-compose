#!/usr/bin/env bash
# One backup run: snapshot /data, then apply the retention policy.
set -euo pipefail

SRC="${BACKUP_SOURCE_DIR:-/data}"
KEEP_DAILY="${RESTIC_KEEP_DAILY:-7}"
KEEP_WEEKLY="${RESTIC_KEEP_WEEKLY:-4}"

echo "[$(date -Iseconds)] backup start: ${SRC}"
restic backup "${SRC}" --tag homelab --host "${HOSTNAME:-homelab}"

echo "[$(date -Iseconds)] forget --keep-daily ${KEEP_DAILY} --keep-weekly ${KEEP_WEEKLY}"
restic forget \
  --tag homelab \
  --keep-daily "${KEEP_DAILY}" \
  --keep-weekly "${KEEP_WEEKLY}" \
  --prune

echo "[$(date -Iseconds)] backup done"
restic snapshots --compact | tail -n 5
