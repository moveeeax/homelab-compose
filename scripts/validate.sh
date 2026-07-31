#!/usr/bin/env bash
# Validate the stack without starting it: render the merged compose model
# and run the Python test suite.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "no .env found, using .env.example for validation"
  ENV_FILE=.env.example
else
  ENV_FILE=.env
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "==> docker compose config"
  docker compose --env-file "$ENV_FILE" config -q
  echo "    ok"
else
  echo "==> docker compose not available, skipping compose render"
fi

echo "==> pytest"
python3 -m pytest -q
