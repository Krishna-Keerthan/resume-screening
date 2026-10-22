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
  line="${line#$'\xef\xbb\xbf'}"             # UTF-8 byte order mark (only the first line has one)
  line="${line#"${line%%[![:space:]]*}"}"    # leading whitespace
  case "$line" in 'export '*) line="${line#export}"; line="${line#"${line%%[![:space:]]*}"}" ;; esac
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

case "${1:-}" in
  storage)  required=(SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_BUCKET) ;;
  database) required=(TEST_SUPABASE_DATABASE_URL) ;;
  *) echo "usage: run_supabase_check.sh storage|database" >&2; exit 2 ;;
esac

# A Supabase target must be confirmed by its project ref (the test checks the value; the host
# test here is only to name the variable when it is missing).
case "${TEST_SUPABASE_DATABASE_URL:-}" in
  *supabase*) [ "$1" = database ] && required+=(CONFIRM_SUPABASE_REF) ;;
esac

# A missing variable must fail the run (pytest would otherwise skip the database test and
# exit 0). Only names are printed, never values.
missing=()
for name in "${required[@]}"; do
  [ -n "${!name:-}" ] || missing+=("$name")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "missing or empty in the environment and in $env_file: ${missing[*]}" >&2
  exit 3
fi

cd "$root/backend"
case "$1" in
  storage)  exec "$python" ../scripts/supabase_smoke_test.py ;;
  database) export RUN_SUPABASE_TESTS=1   # the tests skip without it; only this script opts in
            exec "$python" -m pytest -p no:cacheprovider -q tests/integration/test_supabase_database.py ;;
esac
