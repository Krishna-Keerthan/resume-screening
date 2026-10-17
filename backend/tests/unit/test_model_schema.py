"""Model column definitions that must match what the migrations created."""
from app.models.recruiter import Recruiter


def test_recruiter_is_deleted_has_the_server_default_migration_0002_gave_it():
    column = Recruiter.__table__.c.is_deleted

    assert column.server_default is not None
    assert str(column.server_default.arg) in {"false", "0"}
    assert column.nullable is False
