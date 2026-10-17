"""
config/settings.py

Multi-environment configuration module.
"""

import os
import secrets
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# backend/: the project directory. Render carries only this directory from the build to the
# running service, and the Docker image keeps it at /app.
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _path_env(key: str, default: str) -> str:
    """A path setting as an absolute path; a relative one is relative to backend/, not to the cwd."""
    path = Path(os.getenv(key, default))
    return str(path if path.is_absolute() else BACKEND_DIR / path)


def _list_env(key: str, default: str) -> List[str]:
    return [v.strip() for v in os.getenv(key, default).split(",") if v.strip()]


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _bool_env(key: str, default: bool) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# Base Configuration
# ─────────────────────────────────────────────────────────────────────────────

class BaseConfig:
    """
    Shared configuration for all environments.

    SECRET_KEY is the JWT signing secret.  In production it MUST be set
    via the SECRET_KEY environment variable to a cryptographically random
    value (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`)
    """

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME: str    = "AI Resume Intelligence Platform"
    API_VERSION: str = "v1"
    SECRET_KEY: str  = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_ACCESS_TTL_MINUTES: int = _int_env("JWT_ACCESS_TTL_MINUTES", 15)
    JWT_REFRESH_TTL_DAYS:   int = _int_env("JWT_REFRESH_TTL_DAYS", 7)

    # ── Server ────────────────────────────────────────────────────────────────
    HOST:    str = os.getenv("HOST", "0.0.0.0")
    PORT:    int = _int_env("PORT", 5000)
    WORKERS: int = _int_env("WORKERS", 2)
    # Longest gunicorn lets a request run. Axios gives up at 110 s and Vercel's proxy
    # at 120 s, so this stays between them.
    GUNICORN_TIMEOUT_SECONDS: int = _int_env("GUNICORN_TIMEOUT_SECONDS", 115)

    # ── Reverse proxies and the refresh cookie ────────────────────────────────
    # Proxies in front of the app that each append to X-Forwarded-For. ProxyFix
    # trusts exactly this many entries from the right; 0 ignores the header.
    TRUSTED_PROXY_HOPS:    int  = _int_env("TRUSTED_PROXY_HOPS", 0)
    # TEMPORARY: log the forwarded chain on login to verify TRUSTED_PROXY_HOPS.
    LOG_PROXY_CHAIN:       bool = _bool_env("LOG_PROXY_CHAIN", False)
    REFRESH_COOKIE_SECURE: bool = _bool_env("REFRESH_COOKIE_SECURE", False)

    # ── Database ──────────────────────────────────────────────────────────────
    # create_app() creates missing tables. Production turns this off: its schema
    # is built by `alembic upgrade head` in the start command.
    CREATE_TABLES_ON_STARTUP: bool = True
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO:                bool = False

    # Connections per gunicorn worker: up to DB_POOL_SIZE kept open plus
    # DB_MAX_OVERFLOW extra under load, each waiting up to DB_POOL_TIMEOUT s.
    DB_POOL_SIZE:    int = _int_env("DB_POOL_SIZE", 5)
    DB_MAX_OVERFLOW: int = _int_env("DB_MAX_OVERFLOW", 10)
    DB_POOL_TIMEOUT: int = _int_env("DB_POOL_TIMEOUT", 30)

    # A property, so each instance gets its own dict rather than sharing one
    # mutable class-level dict across all subclasses.
    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> dict:  # type: ignore[override]
        return {
            "pool_pre_ping": True,
            "pool_recycle":  300,
            "pool_size":     self.DB_POOL_SIZE,
            "max_overflow":  self.DB_MAX_OVERFLOW,
            "pool_timeout":  self.DB_POOL_TIMEOUT,
        }

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = _list_env("ALLOWED_ORIGINS", "http://localhost:3000")
    CORS_MAX_AGE:    int       = _int_env("CORS_MAX_AGE", 600)

    # ── File Uploads ──────────────────────────────────────────────────────────
    UPLOAD_FOLDER:      str = os.getenv("UPLOAD_FOLDER", "uploads/")
    MAX_CONTENT_LENGTH: int = _int_env("MAX_UPLOAD_MB", 10) * 1024 * 1024
    MAX_UPLOAD_MB:      int = _int_env("MAX_UPLOAD_MB", 10)
    PARSE_TIMEOUT_SECONDS: int = _int_env("PARSE_TIMEOUT_SECONDS", 30)
    MAX_PARSED_TEXT_CHARS: int = _int_env("MAX_PARSED_TEXT_CHARS", 200_000)
    PARSE_CONCURRENCY: int = _int_env("PARSE_CONCURRENCY", 2)
    DOWNLOAD_URL_TTL_SECONDS: int = _int_env("DOWNLOAD_URL_TTL_SECONDS", 300)
    ALLOWED_EXTENSIONS: set = set(_list_env("ALLOWED_EXTENSIONS", "pdf,docx"))

    # ── File storage (StorageService.from_config) ─────────────────────────────
    STORAGE_PROVIDER:      str = os.getenv("STORAGE_PROVIDER", "local")
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY:    str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")
    CLOUDINARY_FOLDER:     str = os.getenv("CLOUDINARY_FOLDER", "resumes")
    # STORAGE_PROVIDER=supabase. The service-role key is server-side only: it bypasses
    # row-level security, so it is never logged, returned or sent to the browser.
    SUPABASE_URL:              str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_BUCKET:           str = os.getenv("SUPABASE_BUCKET", "")

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL:  str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")

    # ── Embeddings ────────────────────────────────────────────────────────────
    EMBEDDING_MODEL:     str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    EMBEDDING_CACHE_DIR: str = _path_env("EMBEDDING_CACHE_DIR", ".cache/embeddings")
    # Load the model from the local cache only. Set where the model was downloaded at
    # build time (Docker image, Render): otherwise huggingface_hub retries a request per
    # cached file when the network is unreachable. A missing model then fails fast and
    # semantic scoring is reported unavailable.
    EMBEDDING_OFFLINE:   bool = _bool_env("EMBEDDING_OFFLINE", False)
    # Threads torch (and OpenMP, via gunicorn.conf.py) may use. 1 keeps the preloaded
    # master safe to fork and the memory footprint small.
    TORCH_NUM_THREADS:   int = _int_env("TORCH_NUM_THREADS", 1)

    # ── Matching Weights ──────────────────────────────────────────────────────
    WEIGHT_SEMANTIC:        float = _float_env("WEIGHT_SEMANTIC", 0.40)
    WEIGHT_KEYWORD:         float = _float_env("WEIGHT_KEYWORD", 0.35)
    WEIGHT_EXPERIENCE:      float = _float_env("WEIGHT_EXPERIENCE", 0.15)
    WEIGHT_SECTION_QUALITY: float = _float_env("WEIGHT_SECTION_QUALITY", 0.10)

    # ── ATS Score Thresholds ──────────────────────────────────────────────────
    ATS_SCORE_THRESHOLD_EXCELLENT: float = _float_env("ATS_SCORE_THRESHOLD_EXCELLENT", 0.80)
    ATS_SCORE_THRESHOLD_GOOD:      float = _float_env("ATS_SCORE_THRESHOLD_GOOD", 0.65)
    ATS_SCORE_THRESHOLD_FAIR:      float = _float_env("ATS_SCORE_THRESHOLD_FAIR", 0.50)

    # ── Recommendations ───────────────────────────────────────────────────────
    TOP_N_JOB_RECOMMENDATIONS: int = _int_env("TOP_N_JOB_RECOMMENDATIONS", 10)
    TOP_N_ROLE_SUGGESTIONS:    int = _int_env("TOP_N_ROLE_SUGGESTIONS", 4)
    TOP_N_CANDIDATES_PER_JOB:  int = _int_env("TOP_N_CANDIDATES_PER_JOB", 3)

    # ── Groq LLM ──────────────────────────────────────────────────────────────
    GROQ_API_KEY:         str   = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL:           str   = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GROQ_MAX_TOKENS:      int   = _int_env("GROQ_MAX_TOKENS", 1024)
    GROQ_TEMPERATURE:     float = _float_env("GROQ_TEMPERATURE", 0.3)
    GROQ_TIMEOUT_SECONDS: int   = _int_env("GROQ_TIMEOUT_SECONDS", 30)
    # Retries after the first attempt. With the timeout above, one call can take
    # (retries + 1) x timeout plus backoff; startup checks it against the budget.
    GROQ_MAX_RETRIES:     int   = _int_env("GROQ_MAX_RETRIES", 2)
    # Axios gives up at 110 s and gunicorn at 115 s: one call must end well before.
    GROQ_CALL_BUDGET_SECONDS: int = _int_env("GROQ_CALL_BUDGET_SECONDS", 100)
    # Inside one request's budget, an optional call (the improvement plan) is skipped when
    # less than this is left.
    GROQ_OPTIONAL_CALL_MIN_SECONDS: int = _int_env("GROQ_OPTIONAL_CALL_MIN_SECONDS", 25)

    # ── Rate limiting ─────────────────────────────────────────────────────────
    # Per caller: the user id from the access token, else the client IP.
    RATE_LIMIT_DEFAULT:       str = os.getenv("RATE_LIMIT_DEFAULT",       "200 per minute")
    RATE_LIMIT_STORAGE_URL:   str = os.getenv("RATE_LIMIT_STORAGE_URL",   "memory://")
    # Login is limited three ways at once; a request must pass all three.
    RATE_LIMIT_LOGIN_IP:       str = os.getenv("RATE_LIMIT_LOGIN_IP",       "10 per minute")
    RATE_LIMIT_LOGIN_IP_EMAIL: str = os.getenv("RATE_LIMIT_LOGIN_IP_EMAIL", "5 per minute")
    RATE_LIMIT_LOGIN_EMAIL:    str = os.getenv("RATE_LIMIT_LOGIN_EMAIL",    "30 per hour")
    RATE_LIMIT_REGISTER:       str = os.getenv("RATE_LIMIT_REGISTER",       "10 per hour")
    RATE_LIMIT_REFRESH:        str = os.getenv("RATE_LIMIT_REFRESH",        "30 per minute")
    # One budget per user shared by every route that can call Groq.
    RATE_LIMIT_LLM:            str = os.getenv("RATE_LIMIT_LLM",            "10 per minute;100 per day")
    RATE_LIMIT_DOWNLOAD:       str = os.getenv("RATE_LIMIT_DOWNLOAD",       "60 per minute")

    # ── Pagination ────────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = _int_env("DEFAULT_PAGE_SIZE", 20)
    MAX_PAGE_SIZE:     int = _int_env("MAX_PAGE_SIZE", 100)


# ─────────────────────────────────────────────────────────────────────────────
# Environment-Specific Subclasses
# ─────────────────────────────────────────────────────────────────────────────

class DevelopmentConfig(BaseConfig):
    DEBUG:                   bool = True
    TESTING:                 bool = False
    SQLALCHEMY_DATABASE_URI: str  = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_ECHO:         bool = False


class ProductionConfig(BaseConfig):
    DEBUG:      bool = False
    TESTING:    bool = False
    # One worker: the app and its embedding model measured 470 to 500 MB, and two
    # workers 538 MB, against Render's 512 MB (docs/deploy_phase3.md).
    WORKERS: int = _int_env("WORKERS", 1)
    # Quieter than development unless LOG_LEVEL says otherwise. The temporary
    # LOG_PROXY_CHAIN line is a WARNING, so ERROR or above hides it.
    LOG_LEVEL:  str  = os.getenv("LOG_LEVEL", "WARNING")
    CREATE_TABLES_ON_STARTUP: bool = False
    # Vercel's proxy, then Render's. Confirm with LOG_PROXY_CHAIN after a deploy.
    TRUSTED_PROXY_HOPS:    int  = _int_env("TRUSTED_PROXY_HOPS", 2)
    REFRESH_COOKIE_SECURE: bool = _bool_env("REFRESH_COOKIE_SECURE", True)

    def __init__(self) -> None:
        # Enforce a non-default SECRET_KEY in production
        key = os.getenv("SECRET_KEY", "")
        if not key or key == "dev-secret-change-in-production":
            raise EnvironmentError(
                "SECRET_KEY must be set to a cryptographically random value in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        # Per-process counters would give every gunicorn worker its own budget.
        if self.RATE_LIMIT_STORAGE_URL.startswith("memory:"):
            raise EnvironmentError(
                "RATE_LIMIT_STORAGE_URL must point at a shared store (e.g. redis://...) "
                "in production; memory:// keeps a separate counter in every worker."
            )

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:  # type: ignore[override]
        uri = os.getenv("DATABASE_URL")
        if not uri:
            raise EnvironmentError(
                "DATABASE_URL must be set in production. "
                "Set it in Render → Environment Variables."
            )
        if uri.startswith("postgres://"):
            uri = uri.replace("postgres://", "postgresql://", 1)
        return uri


class TestingConfig(BaseConfig):
    DEBUG:                   bool = True
    TESTING:                 bool = True
    SQLALCHEMY_DATABASE_URI: str  = "sqlite:///:memory:"
    WTF_CSRF_ENABLED:        bool = False
    LOG_LEVEL:               str  = "ERROR"
    SECRET_KEY:              str  = "test-secret-key-not-for-production"
    TRUSTED_PROXY_HOPS:      int  = 2
    # Limiter runs for real, but nothing trips it unless a test lowers a limit.
    RATE_LIMIT_DEFAULT:        str = "1000000 per minute"
    RATE_LIMIT_LOGIN_IP:       str = "1000000 per minute"
    RATE_LIMIT_LOGIN_IP_EMAIL: str = "1000000 per minute"
    RATE_LIMIT_LOGIN_EMAIL:    str = "1000000 per minute"
    RATE_LIMIT_REGISTER:       str = "1000000 per minute"
    RATE_LIMIT_REFRESH:        str = "1000000 per minute"
    RATE_LIMIT_LLM:            str = "1000000 per minute"
    RATE_LIMIT_DOWNLOAD:       str = "1000000 per minute"

    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> dict:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Config Registry
# ─────────────────────────────────────────────────────────────────────────────

_CONFIG_REGISTRY: dict = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
}


def get_config(env: str | None = None) -> BaseConfig:
    """
    Return an *instance* of the appropriate config class.

    An instance, not the class: app.config.from_object() only evaluates
    @property settings (e.g. ProductionConfig.SQLALCHEMY_DATABASE_URI) on
    instances.
    """
    resolved     = env or os.getenv("APP_ENV", "development")
    config_class = _CONFIG_REGISTRY.get(resolved)
    if config_class is None:
        valid = ", ".join(_CONFIG_REGISTRY.keys())
        raise ValueError(f"Unknown environment '{resolved}'. Valid options: {valid}")
    return config_class()