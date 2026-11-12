# shellcheck shell=bash
# Backup status as Prometheus metrics, sourced by backup.sh and entrypoint.sh.
# The file lands on a volume shared with node-exporter, whose textfile
# collector exports every *.prom file in that directory.

METRICS_DIR="${BACKUP_METRICS_DIR:-/metrics}"
METRICS_FILE="${METRICS_DIR}/backup.prom"
STALE_AFTER="${BACKUP_STALE_AFTER_SECONDS:-93600}"
# A non-numeric sample would make node-exporter reject the whole file.
if ! [[ "$STALE_AFTER" =~ ^[0-9]+$ ]]; then
  echo "warning: BACKUP_STALE_AFTER_SECONDS='${STALE_AFTER}' is not a number of seconds, using 93600" >&2
  STALE_AFTER=93600
fi

# Values carried over between runs. A failed run only updates the
# last_run_* series, so the last successful values survive it.
last_success_ts=""
last_duration=""
last_bytes_added=""
last_snapshot_count=""
last_run_ts=""
last_run_success=""

# Read the previous values back from the metrics file, if there is one.
metrics_load() {
  [ -f "$METRICS_FILE" ] || return 0
  local name value
  while read -r name value; do
    case "$name" in
      homelab_backup_last_success_timestamp) last_success_ts="$value" ;;
      homelab_backup_duration_seconds) last_duration="$value" ;;
      homelab_backup_bytes_added) last_bytes_added="$value" ;;
      homelab_backup_snapshot_count) last_snapshot_count="$value" ;;
      homelab_backup_last_run_timestamp) last_run_ts="$value" ;;
      homelab_backup_last_run_success) last_run_success="$value" ;;
    esac
  done < "$METRICS_FILE"
}

# _metric NAME HELP VALUE: one gauge in text exposition format; skipped
# while VALUE is empty (e.g. no successful run yet).
_metric() {
  [ -n "$3" ] || return 0
  printf '# HELP %s %s\n# TYPE %s gauge\n%s %s\n' "$1" "$2" "$1" "$1" "$3"
}

# Write the current values. node-exporter may read the directory at any
# moment, so write to a temp file and rename it into place.
metrics_write() {
  mkdir -p "$METRICS_DIR"
  local tmp="${METRICS_FILE}.$$.tmp"
  {
    _metric homelab_backup_last_success_timestamp \
      "Unix time of the last successful backup run." "$last_success_ts"
    _metric homelab_backup_duration_seconds \
      "Wall-clock duration of the last successful run (backup, forget, prune)." "$last_duration"
    _metric homelab_backup_bytes_added \
      "Bytes added to the repository by the last successful run (restic data_added)." "$last_bytes_added"
    _metric homelab_backup_snapshot_count \
      "Snapshots tagged homelab after the last successful run." "$last_snapshot_count"
    _metric homelab_backup_last_run_timestamp \
      "Unix time the last backup run finished, successful or not." "$last_run_ts"
    _metric homelab_backup_last_run_success \
      "1 if the last backup run succeeded, 0 if it failed." "$last_run_success"
    _metric homelab_backup_stale_after_seconds \
      "Age after which the BackupStale alert fires (BACKUP_STALE_AFTER_SECONDS)." "$STALE_AFTER"
  } > "$tmp"
  mv -f "$tmp" "$METRICS_FILE"
}

# notify OUTCOME MESSAGE: optional ping on success/failure. Success goes to
# BACKUP_NOTIFY_URL; failure goes to BACKUP_NOTIFY_FAIL_URL, or to
# ${BACKUP_NOTIFY_URL}/fail (the healthchecks.io convention). The message is
# sent as the POST body, which ntfy shows as the notification text and
# healthchecks.io keeps as the ping log. A failed ping never fails the backup.
notify() {
  local outcome="$1" message="$2" url
  [ -n "${BACKUP_NOTIFY_URL:-}" ] || return 0
  if [ "$outcome" = success ]; then
    url="$BACKUP_NOTIFY_URL"
  else
    url="${BACKUP_NOTIFY_FAIL_URL:-${BACKUP_NOTIFY_URL%/}/fail}"
  fi
  curl -fsS -m 10 --retry 3 -o /dev/null \
    -H "Title: homelab backup ${outcome}" \
    --data-raw "$message" "$url" \
    || echo "[$(date -Iseconds)] warning: notify ${outcome} ping to BACKUP_NOTIFY_URL failed" >&2
}
