#!/usr/bin/env bash
# Restore drill: recover the latest snapshot into a target directory.
#   docker compose exec backup restore.sh /restore-target
set -euo pipefail

TARGET="${1:-/restore}"
SNAPSHOT="${2:-latest}"

echo "restoring snapshot '${SNAPSHOT}' into ${TARGET}"
mkdir -p "${TARGET}"
restic restore "${SNAPSHOT}" --target "${TARGET}"
echo "restore complete: ${TARGET}"
