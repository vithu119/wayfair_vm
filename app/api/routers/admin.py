from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_admin_user, list_all_users

router = APIRouter(prefix="/admin", tags=["admin"])

_RUNS_BASE = Path("outputs/runs")


def _count_runs(user_id: str) -> int:
    user_dir = _RUNS_BASE / user_id
    if not user_dir.exists():
        return 0
    return sum(1 for d in user_dir.iterdir() if (d / "state.json").exists())


@router.get("/users")
async def get_users(_: dict = Depends(get_admin_user)):
    users = list_all_users()
    for user in users:
        user["run_count"] = _count_runs(user["user_id"])
    return users


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    from app.api.user_store import delete_user as _delete
    deleted = _delete(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
