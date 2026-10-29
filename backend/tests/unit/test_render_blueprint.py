"""
render.yaml is Render's Blueprint file. Render looks for it in the repository root, and a
service uses runtime: docker: Render builds backend/Dockerfile and runs its CMD.

Field names are the ones in https://render.com/docs/blueprint-spec and
https://render.com/schema/render.yaml.json.
"""
import os

import pytest
import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture(scope="module")
def blueprint():
    with open(os.path.join(_REPO, "render.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def web(blueprint):
    (service,) = [s for s in blueprint["services"] if s["type"] == "web"]
    return service


def test_the_blueprint_is_in_the_repository_root_only():
    assert os.path.isfile(os.path.join(_REPO, "render.yaml"))
    assert not os.path.exists(os.path.join(_REPO, "backend", "render.yaml"))


def test_the_web_service_builds_the_backend_dockerfile(web):
    # Both paths are given from the repository root, with no rootDir: Render's schema words
    # dockerfilePath and dockerContext as relative to rootDir in one place and to the repo
    # root in another, and the two readings agree only when rootDir is unset.
    assert web["runtime"] == "docker"
    assert "rootDir" not in web
    assert web["dockerfilePath"] == "./backend/Dockerfile"
    assert web["dockerContext"] == "./backend"
    assert os.path.isfile(os.path.join(_REPO, web["dockerfilePath"]))
    assert os.path.isdir(os.path.join(_REPO, web["dockerContext"]))


def test_the_web_service_has_no_build_or_start_command_of_its_own(web):
    # The Dockerfile builds the image and its CMD (start.sh) starts it.
    for field in ("buildCommand", "startCommand", "dockerCommand", "preDeployCommand"):
        assert field not in web


def test_the_web_service_declares_its_environment(web):
    env = {e["key"]: e for e in web["envVars"]}

    assert {k: env[k].get("value") for k in ("APP_ENV", "STORAGE_PROVIDER", "LOG_LEVEL", "TRUSTED_PROXY_HOPS", "LOG_PROXY_CHAIN")} == {
        "APP_ENV": "production",
        "STORAGE_PROVIDER": "supabase",
        "LOG_LEVEL": "INFO",
        "TRUSTED_PROXY_HOPS": "2",
        "LOG_PROXY_CHAIN": "true",
    }
    assert env["SECRET_KEY"] == {"key": "SECRET_KEY", "generateValue": True}
    for secret in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_BUCKET", "GROQ_API_KEY", "ALLOWED_ORIGINS"):
        assert env[secret] == {"key": secret, "sync": False}
    assert "value" not in env["RATE_LIMIT_STORAGE_URL"] and "fromService" in env["RATE_LIMIT_STORAGE_URL"]


def test_the_model_cache_setting_lives_in_the_dockerfile_only(web):
    assert "EMBEDDING_OFFLINE" not in {e["key"] for e in web["envVars"]}
    with open(os.path.join(_REPO, "backend", "Dockerfile"), encoding="utf-8") as f:
        assert "ENV EMBEDDING_OFFLINE=true" in f.read()


def test_the_key_value_store_declares_who_may_connect(blueprint):
    (store,) = [s for s in blueprint["services"] if s["type"] == "keyvalue"]

    assert "ipAllowList" in store      # required by the schema for keyvalue services


def test_the_blueprint_leaves_the_worker_count_to_the_config_default(web):
    # Render's 512 MB fits one worker (docs/deploy_phase3.md); the default lives in config only.
    assert "WORKERS" not in {e["key"] for e in web["envVars"]}



def test_the_database_is_external_so_the_blueprint_declares_none(blueprint, web):
    # Postgres lives on Supabase; DATABASE_URL is a secret set in the Render dashboard.
    assert "databases" not in blueprint
    (url,) = [e for e in web["envVars"] if e["key"] == "DATABASE_URL"]
    assert url == {"key": "DATABASE_URL", "sync": False}
    assert "fromDatabase" not in str(blueprint)


def test_render_health_checks_the_liveness_endpoint_only(web):
    # /health makes no database or storage call (test_health.py); /health/ready and
    # /health/services do, and must stay out of Render's path.
    assert web["healthCheckPath"] == "/api/v1/health"


def test_the_web_service_logs_at_info(web):
    env = {e["key"]: e.get("value") for e in web["envVars"]}

    assert env["LOG_LEVEL"] == "INFO"
