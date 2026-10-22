#!/usr/bin/env bash
# Runs one of the manual Supabase checks (docs/supabase-checks.md) with the variables from
# backend/.env. Usage: run_supabase_check.sh storage|database
# ENV_FILE overrides the file to load.
#
# The file is parsed, not sourced: a value is taken literally, so `&`, `$`, backticks and
# `$(...)` in a password are neither run nor expanded. Values are exported into this
# process's environment only (never into an argument list, so `ps` does not show them) and
# are never echoed. No `set -x`.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ENV_FILE:-$root/backend/.env}"
python="${PYTHON:-$HOME/ats-venv311/bin/python}"

[ -f "$env_file" ] || { echo "no env file at $env_file" >&2; exit 2; }

while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"                       # Windows line ending
  case "$line" in ''|'#'*) continue ;; esac
  case "$line" in *=*) ;; *) continue ;; esac
  key="${line%%=*}"
  value="${line#*=}"
  case "$key" in [A-Za-z_]*) ;; *) continue ;; esac
  case "$key" in *[!A-Za-z0-9_]*) continue ;; esac
  case "$value" in                           # one pair of surrounding quotes
    \"*\") value="${value#\"}"; value="${value%\"}" ;;
    \'*\') value="${value#\'}"; value="${value%\'}" ;;
  esac
  export "$key=$value"
done < "$env_file"

cd "$root/backend"
case "${1:-}" in
  storage)
    exec "$python" ../scripts/supabase_smoke_test.py ;;
  database)
    exec "$python" -m pytest -p no:cacheprovider -q tests/integration/test_supabase_database.py ;;
  *)
    echo "usage: run_supabase_check.sh storage|database" >&2; exit 2 ;;
esac
