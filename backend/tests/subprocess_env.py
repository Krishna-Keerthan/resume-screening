"""
The environment for a subprocess that a test starts (Alembic, gunicorn.conf.py, a settings probe).

Built from nothing instead of copied from os.environ, so a developer's shell cannot change a
result. Overrides are explicit.
"""
import os
from pathlib import Path

# A directory with a sitecustomize.py that stops python-dotenv loading a .env file. The
# subprocess runs config/settings.py, which calls load_dotenv() on import; python-dotenv 1.0.1
# has no switch to turn that off.
_GUARD = str(Path(__file__).parent / "subprocess_guard")
_KEPT = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")


def subprocess_env(**overrides):
    environment = {k: os.environ[k] for k in _KEPT if k in os.environ}
    environment["PYTHONPATH"] = os.pathsep.join([_GUARD, *filter(None, [overrides.pop("PYTHONPATH", None)])])
    environment.update(overrides)
    return environment
