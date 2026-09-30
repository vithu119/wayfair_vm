from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import authenticate_user, create_access_token, create_user, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool = False


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest):
    user = create_user(body.username, body.password)
    token = create_access_token(user["user_id"], user["username"], user["is_admin"])
    return TokenResponse(access_token=token, username=user["username"], is_admin=user["is_admin"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    from fastapi import HTTPException
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(user["user_id"], user["username"], user["is_admin"])
    return TokenResponse(access_token=token, username=user["username"], is_admin=user["is_admin"])


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user["user_id"],
        "username": current_user["username"],
        "is_admin": current_user.get("is_admin", False),
    }
