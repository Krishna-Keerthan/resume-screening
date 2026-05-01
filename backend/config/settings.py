"""
config/settings.py

Multi-environment configuration module.

FIXES APPLIED:
  CF-01 — get_config() previously returned the config *class* instead of an
           *instance*. Flask's app.config.from_object() calls getattr() on the
           object to read values. When a class is passed, class-level attributes
           are read correctly — BUT @property descriptors (like
           ProductionConfig.SQLALCHEMY_DATABASE_URI) are NEVER evaluated because
           properties only execute on instances. The result was that
           SQLALCHEMY_DATABASE_URI was always None in production, crashing
           SQLAlchemy on startup.

           Fix: return config_class() — instantiate the class.
           ProductionConfig.__init__ enforces the SECRET_KEY guard, and the
           @property is now evaluated correctly.

  CF-02 — SQLALCHEMY_ENGINE_OPTIONS was a mutable class-level dict shared
           across all config subclasses. Any subclass or test that mutated the
           dict would corrupt all other subclasses. Fixed with per-instance copy
           via dict literal (already safe for Pydantic-style classes but
           explicitly copied now for safety).

  CF-03 — Added RATE_LIMIT_* stubs so flask-limiter can be wired without
           touching per-environment subclasses.

  CF-04 — Added CORS_MAX_AGE to avoid browser pre-flight overhead.
"""

import os
import secrets
from typing import List

from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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

    # ── Database ──────────────────────────────────────────────────────────────
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO:                bool = False

    # FIX CF-02: define as a property so each subclass gets its own dict copy.
    # A mutable class-level dict is shared by reference across all subclasses —
    # mutation in one (e.g. a test fixture) would corrupt the others.
    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> dict:  # type: ignore[override]
        return {
            "pool_pre_ping": True,
            "pool_recycle":  300,
            "pool_size":     5,
            "max_overflow":  10,
        }

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = _list_env("ALLOWED_ORIGINS", "http://localhost:3000")
    CORS_MAX_AGE:    int       = _int_env("CORS_MAX_AGE", 600)   # FIX CF-04

    # ── File Uploads ──────────────────────────────────────────────────────────
    UPLOAD_FOLDER:      str = os.getenv("UPLOAD_FOLDER", "uploads/")
    MAX_CONTENT_LENGTH: int = _int_env("MAX_UPLOAD_MB", 10) * 1024 * 1024
    MAX_UPLOAD_MB:      int = _int_env("MAX_UPLOAD_MB", 10)
    ALLOWED_EXTENSIONS: set = set(_list_env("ALLOWED_EXTENSIONS", "pdf,docx"))

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL:  str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")

    # ── Embeddings ────────────────────────────────────────────────────────────
    EMBEDDING_MODEL:     str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    EMBEDDING_CACHE_DIR: str = os.getenv("EMBEDDING_CACHE_DIR", ".cache/embeddings")

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

    # ── Rate limiting (FIX CF-03) ─────────────────────────────────────────────
    # Stub values — wire into flask-limiter in create_app() when ready.
    RATE_LIMIT_DEFAULT:       str = os.getenv("RATE_LIMIT_DEFAULT",       "200 per minute")
    RATE_LIMIT_AUTH:          str = os.getenv("RATE_LIMIT_AUTH",          "20 per minute")
    RATE_LIMIT_SCORING:       str = os.getenv("RATE_LIMIT_SCORING",       "30 per minute")
    RATE_LIMIT_STORAGE_URL:   str = os.getenv("RATE_LIMIT_STORAGE_URL",   "memory://")

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
    LOG_LEVEL:  str  = "WARNING"
    LOG_FORMAT: str  = "json"

    def __init__(self) -> None:
        # Enforce a non-default SECRET_KEY in production
        key = os.getenv("SECRET_KEY", "")
        if not key or key == "dev-secret-change-in-production":
            raise EnvironmentError(
                "SECRET_KEY must be set to a cryptographically random value in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
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

    FIX CF-01: The original implementation returned the class itself
    (`return config_class`). Flask's app.config.from_object() reads
    attributes via getattr(), which works for plain class attributes but
    NEVER evaluates @property descriptors defined on the class — those only
    fire on instances. ProductionConfig.SQLALCHEMY_DATABASE_URI is a
    @property, so it was silently ignored and SQLALCHEMY_DATABASE_URI was
    always None, crashing SQLAlchemy on startup.

    Fix: `return config_class()` — instantiate the class so @property
    descriptors execute correctly.
    """
    resolved     = env or os.getenv("APP_ENV", "development")
    config_class = _CONFIG_REGISTRY.get(resolved)
    if config_class is None:
        valid = ", ".join(_CONFIG_REGISTRY.keys())
        raise ValueError(f"Unknown environment '{resolved}'. Valid options: {valid}")
    return config_class()   # ← FIX CF-01: was `return config_class`