#!/usr/bin/env bash
# Manual check of migration 0003's data paths on a THROWAWAY PostgreSQL database.
# Destroys everything in that database (downgrades to base first).
#
#   export DATABASE_URL=postgresql://postgres:test@localhost:55432/ats_migr
#   PSQL="psql $DATABASE_URL" ./migrations/verify_0003.sh      # run from backend/
#
# PSQL is any command that reads SQL on its own arguments, e.g.
#   PSQL="docker exec ats_pg_test psql -U postgres -d ats_migr"
set -euo pipefail
: "${DATABASE_URL:?set DATABASE_URL to a throwaway database}"
: "${PSQL:?set PSQL to a psql command for the same database}"
P="$PSQL -v ON_ERROR_STOP=1 -q"
C="INSERT INTO candidates (id, full_name, email, is_active, is_deleted, open_to_work, created_at, updated_at) VALUES"
R="INSERT INTO recruiters (id, full_name, email, company_name, is_active, platform_rank, total_hires, total_jobs_posted, created_at, updated_at) VALUES"

alembic downgrade base >/dev/null 2>&1
alembic upgrade 0002 >/dev/null 2>&1
$P -c "$C ('c1','A','  Mixed.Case@Example.COM ',true,false,true,now(),now()),('c2','B','other@example.com',true,false,true,now(),now()),('c3','C','OTHER@example.com ',true,true,true,now(),now())" \
   -c "$R ('r1','R','Rec@Example.com','Co',true,0,0,0,now(),now())"

echo "1. duplicate pair (one soft-deleted): upgrade must refuse, list both rows, and stay at 0002"
out=$(alembic upgrade head 2>&1 || true)
echo "$out" | grep -E "^(candidates|recruiters):"
echo "$out" | grep -q "Cannot make emails" || { echo "FAIL: no refusal"; exit 1; }
alembic current 2>/dev/null | grep -q "^0002" || { echo "FAIL: revision moved"; exit 1; }
[ "$($P -tA -c "SELECT email FROM candidates WHERE id='c1'")" = "  Mixed.Case@Example.COM " ] || { echo "FAIL: data changed"; exit 1; }

echo "2. remove the duplicate: upgrade normalises with lower(trim(email))"
$P -c "DELETE FROM candidates WHERE id='c3'"
alembic upgrade head >/dev/null 2>&1
[ "$($P -tA -c "SELECT email FROM candidates WHERE id='c1'")" = "mixed.case@example.com" ] || { echo "FAIL: candidate not normalised"; exit 1; }
[ "$($P -tA -c "SELECT email FROM recruiters WHERE id='r1'")" = "rec@example.com" ] || { echo "FAIL: recruiter not normalised"; exit 1; }

echo "3. the unique index rejects a case variant"
out=$($P -c "$C ('c4','D','OTHER@EXAMPLE.COM',true,false,true,now(),now())" 2>&1 || true)
echo "$out" | grep -q uq_candidates_email_lower || { echo "FAIL: not rejected"; exit 1; }

echo "4. alembic check is clean"
alembic check 2>&1 | grep -q "No new upgrade operations detected" || { echo "FAIL: drift"; exit 1; }
echo "OK"
