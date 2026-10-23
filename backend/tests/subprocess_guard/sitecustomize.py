"""Python imports this at start-up in every subprocess whose PYTHONPATH holds this directory
(see tests/subprocess_env.py). It does for the subprocess what tests/conftest.py does for the
test session: config/settings.py finds no .env file to load."""
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
