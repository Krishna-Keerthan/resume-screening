"""Model column definitions that must match what the migrations created."""
from app.models.recruiter import Recruiter


def test_recruiter_is_deleted_has_the_server_default_migration_0002_gave_it():
    column = Recruiter.__table__.c.is_deleted

    assert column.server_default is not None
    assert str(column.server_default.arg) in {"false", "0"}
    assert column.nullable is False


# ─── resumes.storage_key comment ──────────────────────────────────────────────

def test_the_storage_key_comment_describes_the_current_stores():
    from app.models.resume import Resume

    comment = Resume.__table__.c.storage_key.comment

    assert "cloudinary" not in comment.lower()
    assert "supabase" in comment.lower() and "local" in comment.lower()


def test_migration_0004_sets_the_comment_the_model_declares():
    # alembic check does not compare column comments, so this keeps model and migration together
    import glob
    import importlib.util
    import os

    from app.models.resume import Resume

    (path,) = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                     "migrations", "versions", "*_0004_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0004", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.NEW_COMMENT == Resume.__table__.c.storage_key.comment
    assert (migration.revision, migration.down_revision) == ("0004", "0003")
    assert "Cloudinary" in migration.OLD_COMMENT        # what the downgrade restores
