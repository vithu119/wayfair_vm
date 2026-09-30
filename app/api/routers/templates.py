from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from app.analyser.registration_workflow import register_workbook
from app.analyser.template_registry import TemplateRegistry
from app.api.auth import get_current_user
from app.api.models import (
    RegistrationResultOut,
    TemplateEntryOut,
    ActivateTemplateResponse,
)

router = APIRouter(prefix="/templates", tags=["templates"])

_UPLOAD_BASE = Path("outputs/uploads")
_PROFILE_BASE = Path("outputs/template_profiles")
_REGISTRY_BASE = Path("outputs/template_registry")


def _upload_dir(user_id: str) -> Path:
    return _UPLOAD_BASE / user_id


def _profile_dir(user_id: str) -> Path:
    return _PROFILE_BASE / user_id


def _registry_json(user_id: str) -> Path:
    return _REGISTRY_BASE / user_id / "template_registry.json"


def _registry_csv(user_id: str) -> Path:
    return _REGISTRY_BASE / user_id / "template_registry.csv"


def _load_registry(user_id: str) -> TemplateRegistry:
    return TemplateRegistry.load(_registry_json(user_id))


def _save_registry(user_id: str, registry: TemplateRegistry) -> None:
    registry.save(_registry_json(user_id), _registry_csv(user_id))


@router.post("/upload", response_model=list[RegistrationResultOut])
async def upload_templates(
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    ud = _upload_dir(current_user["user_id"])
    pd = _profile_dir(current_user["user_id"])
    ud.mkdir(parents=True, exist_ok=True)
    pd.mkdir(parents=True, exist_ok=True)
    registry = _load_registry(current_user["user_id"])
    results = []

    for upload in files:
        dest = ud / upload.filename
        content = await upload.read()
        dest.write_bytes(content)

        try:
            result = register_workbook(dest, pd, registry)
        except Exception as exc:
            results.append(RegistrationResultOut(
                template_id="",
                filename=upload.filename,
                fill_status="not_fillable",
                blocking_reasons=[str(exc)],
                warnings=[],
                error=str(exc),
            ))
            continue

        results.append(RegistrationResultOut(
            template_id=result.template_id,
            filename=result.filename,
            fill_status=result.fill_status,
            blocking_reasons=result.blocking_reasons,
            warnings=result.warnings,
            safe_write_start_row=result.safe_write_start_row,
            error=result.error,
        ))

    _save_registry(current_user["user_id"], registry)
    return results


@router.get("", response_model=list[TemplateEntryOut])
async def list_templates(current_user: dict = Depends(get_current_user)):
    registry = _load_registry(current_user["user_id"])
    entries = registry.get_active()
    return [
        TemplateEntryOut(
            template_id=e.template_id,
            filename=e.filename,
            category=e.category,
            category_status=e.category_status,
            template_purpose=e.template_purpose,
            fill_status=e.fill_status,
            listing_sheet=e.listing_sheet,
            header_row=e.header_row,
            safe_write_start_row=e.safe_write_start_row,
            is_active=e.is_active,
            warnings=e.warnings,
            blocking_reasons=e.blocking_reasons,
            analysis_timestamp=e.analysis_timestamp,
            registration_timestamp=e.registration_timestamp,
        )
        for e in entries
    ]


@router.get("/{template_id}")
async def get_template(template_id: str, current_user: dict = Depends(get_current_user)):
    registry = _load_registry(current_user["user_id"])
    entry = registry.find_by_id(template_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Template {template_id!r} not found")

    pd = _profile_dir(current_user["user_id"])
    profile_data = None
    candidates = [
        Path(entry.profile_path),
        Path("outputs") / entry.profile_path,
        pd / Path(entry.profile_path).name,
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                profile_data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                pass
            break

    return {
        "template_id": entry.template_id,
        "filename": entry.filename,
        "category": entry.category,
        "category_status": entry.category_status,
        "template_purpose": entry.template_purpose,
        "fill_status": entry.fill_status,
        "listing_sheet": entry.listing_sheet,
        "header_row": entry.header_row,
        "safe_write_start_row": entry.safe_write_start_row,
        "is_active": entry.is_active,
        "warnings": entry.warnings,
        "blocking_reasons": entry.blocking_reasons,
        "analysis_timestamp": entry.analysis_timestamp,
        "registration_timestamp": entry.registration_timestamp,
        "profile": profile_data,
    }


@router.post("/{template_id}/reanalyse")
async def reanalyse_template(template_id: str, current_user: dict = Depends(get_current_user)):
    registry = _load_registry(current_user["user_id"])
    entry = registry.find_by_id(template_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Template {template_id!r} not found")
    upload_path = _upload_dir(current_user["user_id"]) / entry.filename
    if not upload_path.exists():
        raise HTTPException(status_code=404, detail=f"Template file not found on disk: {entry.filename}")
    try:
        registry._entries = [e for e in registry._entries if e.template_id != template_id]
        result = register_workbook(upload_path, _profile_dir(current_user["user_id"]), registry)
        _save_registry(current_user["user_id"], registry)
        return {"template_id": result.template_id, "fill_status": result.fill_status,
                "warnings": result.warnings, "blocking_reasons": result.blocking_reasons}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    uid = current_user["user_id"]
    registry = _load_registry(uid)
    entry = registry.find_by_id(template_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Template {template_id!r} not found")
    upload_file = _upload_dir(uid) / entry.filename
    profile_file = _profile_dir(uid) / (Path(entry.profile_path).name if entry.profile_path else "")
    if upload_file.exists():
        upload_file.unlink()
    if profile_file.exists():
        profile_file.unlink()
    registry._entries = [e for e in registry._entries if e.template_id != template_id]
    _save_registry(uid, registry)
    return {"deleted": True}


@router.delete("")
async def delete_all_templates(current_user: dict = Depends(get_current_user)):
    uid = current_user["user_id"]
    for d in [_upload_dir(uid), _profile_dir(uid), _registry_json(uid).parent]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    return {"deleted": True}


@router.post("/{template_id}/activate", response_model=ActivateTemplateResponse)
async def activate_template(template_id: str, current_user: dict = Depends(get_current_user)):
    registry = _load_registry(current_user["user_id"])
    entry = registry.find_by_id(template_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Template {template_id!r} not found")
    entry.is_active = True
    _save_registry(current_user["user_id"], registry)
    return ActivateTemplateResponse(template_id=template_id, is_active=True)
