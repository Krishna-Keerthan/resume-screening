"""
Resume JSON columns must create on SQLite (tests/dev) and stay JSONB on PostgreSQL.
"""
import pytest
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.models.resume import Resume

JSON_COLUMNS = [
    "skills", "education", "experience", "certifications",
    "projects", "contact_info", "oov_skills_list",
]


def test_resume_table_ddl_compiles_on_sqlite():
    ddl = str(CreateTable(Resume.__table__).compile(dialect=sqlite.dialect()))
    assert "JSONB" not in ddl


@pytest.mark.parametrize("column", JSON_COLUMNS)
def test_resume_json_column_is_jsonb_on_postgresql(column):
    col_type = Resume.__table__.c[column].type
    compiled = col_type.compile(dialect=postgresql.dialect())
    assert compiled == "JSONB"
