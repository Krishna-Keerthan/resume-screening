"""
scripts/reset_app_tables.sql drops every table the application owns, and nothing else. It is
generated from the models' metadata plus alembic_version by backend/scripts/generate_reset_sql.py;
this test keeps the committed file equal to what the generator produces.
"""
import os
import re

import pytest

from app.core.database import db
from scripts.generate_reset_sql import render

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_FILE = os.path.join(_REPO, "scripts", "reset_app_tables.sql")


@pytest.fixture(scope="module")
def committed():
    with open(_FILE, encoding="utf-8") as f:
        return f.read()


def _statements(sql):
    lines = [l for l in sql.splitlines() if l.strip() and not l.lstrip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def test_the_committed_file_is_what_the_generator_produces(committed):
    assert committed == render()


def test_the_header_says_to_review_before_running(committed):
    header = committed.split("DROP TABLE", 1)[0].lower()

    assert "review" in header and "before" in header
    assert "destroys" in header or "deletes" in header


def test_every_statement_is_a_drop_table_if_exists(committed):
    statements = _statements(committed)

    assert statements
    assert all(re.fullmatch(r'DROP TABLE IF EXISTS "[a-z_]+"', s) for s in statements)


def test_it_never_touches_a_schema_or_cascades(committed):
    lowered = committed.lower()

    for forbidden in ("drop schema", "cascade", "truncate", "delete from", "drop type", "drop role"):
        assert forbidden not in lowered


def test_it_drops_every_model_table_and_alembic_version(committed):
    dropped = {re.search(r'"(.+)"', s).group(1) for s in _statements(committed)}

    assert dropped == {t.name for t in db.metadata.tables.values()} | {"alembic_version"}
    assert {"candidates", "recruiters", "jobs", "resumes", "applications", "ats_scores", "refresh_tokens"} <= dropped


def test_a_table_is_dropped_before_the_tables_it_references(committed):
    order = [re.search(r'"(.+)"', s).group(1) for s in _statements(committed)]

    for table in db.metadata.sorted_tables:
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent != table.name:
                assert order.index(table.name) < order.index(parent), f"{table.name} must go before {parent}"
