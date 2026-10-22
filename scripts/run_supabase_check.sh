#!/usr/bin/env bash
# Runs one of the manual Supabase checks (docs/supabase-checks.md) with the variables from
# backend/.env, without printing them. Usage: run_supabase_check.sh storage|database
# ENV_FILE overrides the file to load.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ENV_FILE:-$root/backend/.env}"
python="${PYTHON:-$HOME/ats-venv311/bin/python}"

[ -f "$env_file" ] || { echo "no env file at $env_file" >&2; exit 2; }

# tr strips Windows line endings, which would otherwise end up inside the values.
set -a
. <(tr -d '\r' < "$env_file")
set +a

cd "$root/backend"
case "${1:-}" in
  storage)
    exec "$python" ../scripts/supabase_smoke_test.py ;;
  database)
    exec "$python" -m pytest -p no:cacheprovider -q tests/integration/test_supabase_database.py ;;
  *)
    echo "usage: run_supabase_check.sh storage|database" >&2; exit 2 ;;
esac
