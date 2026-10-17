"""
app/core/proxy_chain_log.py

TEMPORARY - remove this module, its call in app/__init__.py, the LOG_PROXY_CHAIN
setting and its tests once TRUSTED_PROXY_HOPS has been verified on the real
deployment (see docs/deploy_phase3.md).

With LOG_PROXY_CHAIN on, each login request logs one WARNING with the raw
X-Forwarded-For header, the configured hop count and the client address the
app derived from them. Addresses only: no cookies, tokens or other headers.
"""
import logging

from flask import Flask, current_app, request

logger = logging.getLogger(__name__)

_LOGIN_PATH = "/api/v1/auth/login"
_MAX_CHAIN_CHARS = 300


def register_proxy_chain_log(app: Flask) -> None:
    @app.before_request
    def _log_proxy_chain() -> None:
        if request.path != _LOGIN_PATH or not current_app.config["LOG_PROXY_CHAIN"]:
            return
        logger.warning(
            "TEMPORARY proxy chain check",
            extra={
                "forwarded_for": request.headers.get("X-Forwarded-For", "")[:_MAX_CHAIN_CHARS],
                "trusted_hops":  current_app.config["TRUSTED_PROXY_HOPS"],
                "client_ip":     request.remote_addr,
            },
        )
