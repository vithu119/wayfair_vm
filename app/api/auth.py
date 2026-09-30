from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production-use-a-long-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

_bearer = HTTPBearer()


def _is_admin(username: str) -> bool:
    admins = {u.strip().lower() for u in os.getenv("ADMIN_USERS", "").split(",") if u.strip()}
    return username.lower() in admins


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode(), hashed.encode())


# ── user store (DB-backed) ────────────────────────────────────────────────────

def list_all_users() -> list[dict]:
    from app.api.user_store import list_all_users as _list
    rows = _list()
    return [
        {**r, "is_admin": _is_admin(r["username"])}
        for r in rows
    ]


def create_user(username: str, password: str) -> dict:
    from app.api.user_store import create_user as _create
    user_id = str(uuid.uuid4())
    try:
        _create(username, user_id, _hash_password(password))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"user_id": user_id, "username": username, "is_admin": _is_admin(username)}


def authenticate_user(username: str, password: str) -> Optional[dict]:
    from app.api.user_store import get_user
    user = get_user(username)
    if not user:
        return None
    if not _verify_password(password, user["hashed_password"]):
        return None
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "is_admin": _is_admin(user["username"]),
    }


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str, username: str, is_admin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "username": username, "is_admin": is_admin, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        if not user_id or not username:
            raise exc
    except JWTError:
        raise exc
    return {
        "user_id": user_id,
        "username": username,
        "is_admin": _is_admin(username),
    }


def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
