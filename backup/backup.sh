#!/usr/bin/env bash
# One backup run: snapshot /data, then apply the retention policy.
# The outcome is written to ${BACKUP_METRICS_DIR}/backup.prom for
# node-exporter and, if BACKUP_NOTIFY_URL is set, pinged out.
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=metrics.sh
source "$(dirname "${BASH_SOURCE[0]}")/metrics.sh"

SRC="${BACKUP_SOURCE_DIR:-/data}"
KEEP_DAILY="${RESTIC_KEEP_DAILY:-7}"
KEEP_WEEKLY="${RESTIC_KEEP_WEEKLY:-4}"

START=$(date +%s)
SUMMARY=$(mktemp)

# Any non-zero exit (including restic's 3, "some source data could not be
# read") counts as a failed run: record it and send the failure ping.
on_exit() {
  local rc=$?
  rm -f "$SUMMARY"
  [ "$rc" -eq 0 ] && return 0
  last_run_ts=$(date +%s)
  last_run_success=0
  metrics_write || true
  echo "[$(date -Iseconds)] backup FAILED (exit ${rc})" >&2
  notify failure "homelab backup failed with exit code ${rc} on ${HOSTNAME:-homelab}"
}
trap on_exit EXIT

metrics_load

echo "[$(date -Iseconds)] backup start: ${SRC}"
restic backup "${SRC}" --tag homelab --host "${HOSTNAME:-homelab}" --json > "$SUMMARY"
BYTES_ADDED=$(jq -r 'select(.message_type == "summary") | .data_added' "$SUMMARY" | tail -n 1)
jq -r 'select(.message_type == "summary") |
  "snapshot \(.snapshot_id // "-"): \(.files_new) new, \(.files_changed) changed, \(.data_added) bytes added"' \
  "$SUMMARY"

echo "[$(date -Iseconds)] forget --keep-daily ${KEEP_DAILY} --keep-weekly ${KEEP_WEEKLY}"
restic forget \
  --tag homelab \
  --keep-daily "${KEEP_DAILY}" \
  --keep-weekly "${KEEP_WEEKLY}" \
  --prune

SNAPSHOTS=$(restic snapshots --tag homelab --json | jq 'length')

END=$(date +%s)
last_success_ts=$END
last_duration=$((END - START))
last_bytes_added=${BYTES_ADDED:-0}
last_snapshot_count=$SNAPSHOTS
last_run_ts=$END
last_run_success=1
metrics_write

echo "[$(date -Iseconds)] backup done in ${last_duration}s, ${SNAPSHOTS} snapshots"
restic snapshots --compact | tail -n 5 || true
notify success "homelab backup ok in ${last_duration}s: ${last_bytes_added} bytes added, ${SNAPSHOTS} snapshots"
