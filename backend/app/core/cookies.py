"""
app/core/cookies.py

The refresh-token cookie, set and cleared in one place.

The browser reaches the API through the frontend's own domain (Next.js
rewrites /api/v1/* to the backend), so this is a first-party cookie: host-only
(no Domain), Path=/ so the Next.js middleware sees it on page requests,
HttpOnly, SameSite=Lax. Whether it is Secure and how long it lives come from
config (REFRESH_COOKIE_SECURE, JWT_REFRESH_TTL_DAYS).
"""
from flask import current_app

REFRESH_COOKIE_NAME = "refresh_token"

_PATH = "/"
_SAMESITE = "Lax"
_SECONDS_PER_DAY = 24 * 60 * 60


def _set(response, value: str, max_age: int) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        value,
        max_age=max_age,
        httponly=True,
        secure=current_app.config["REFRESH_COOKIE_SECURE"],
        samesite=_SAMESITE,
        path=_PATH,
    )


def set_refresh_cookie(response, refresh_token: str) -> None:
    _set(response, refresh_token, current_app.config["JWT_REFRESH_TTL_DAYS"] * _SECONDS_PER_DAY)


def clear_refresh_cookie(response) -> None:
    _set(response, "", 0)
