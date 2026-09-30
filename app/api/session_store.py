from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_BASE = Path("outputs/runs")
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dir(user_id: str, run_id: str) -> Path:
    return _BASE / user_id / run_id


def _state_path(user_id: str, run_id: str) -> Path:
    return _run_dir(user_id, run_id) / "state.json"


def _default_run(run_id: str, user_id: str) -> dict:
    now = _now()
    return {
        "run_id": run_id,
        "user_id": user_id,
        "status": "created",
        "uploaded_templates": [],
        "source_files": [],
        "asins": [],
        "resolved_products": [],
        "manual_edits": {},
        "validation_findings": [],
        "export_files": [],
        "created_at": now,
        "updated_at": now,
    }


class RunStore:
    def create_run(self, user_id: str) -> str:
        run_id = str(uuid.uuid4())
        with _LOCK:
            d = _run_dir(user_id, run_id)
            d.mkdir(parents=True, exist_ok=True)
            state = _default_run(run_id, user_id)
            _state_path(user_id, run_id).write_text(
                json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return run_id

    def get_run(self, user_id: str, run_id: str) -> dict | None:
        p = _state_path(user_id, run_id)
        if not p.exists():
            return None
        with _LOCK:
            return json.loads(p.read_text(encoding="utf-8"))

    def update_run(self, user_id: str, run_id: str, **fields: Any) -> dict | None:
        with _LOCK:
            p = _state_path(user_id, run_id)
            if not p.exists():
                return None
            state = json.loads(p.read_text(encoding="utf-8"))
            for k, v in fields.items():
                state[k] = v
            state["updated_at"] = _now()
            p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            return state

    def list_runs(self, user_id: str) -> list[dict]:
        runs = []
        user_dir = _BASE / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            for d in sorted(user_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                p = d / "state.json"
                if p.exists():
                    try:
                        runs.append(json.loads(p.read_text(encoding="utf-8")))
                    except Exception:
                        pass
        return runs

    def export_dir(self, user_id: str, run_id: str) -> Path:
        return _run_dir(user_id, run_id) / "exports"


run_store = RunStore()
