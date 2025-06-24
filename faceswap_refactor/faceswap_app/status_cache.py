
from datetime import datetime, timezone
from typing import Any, Dict

_WORKFLOWS: Dict[str, Dict[str, Any]] = {}

def update_workflow_status(prompt_id: str, status: str, progress: Any | None = None, result_url: str | None = None, error: str | None = None) -> None:
    doc = _WORKFLOWS.setdefault(prompt_id, {
        "prompt_id": prompt_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    doc.update(
        status=status,
        progress=progress or {},
        result=result_url,
        error=error,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

def get_workflow_status(prompt_id: str) -> Dict[str, Any] | None:
    return _WORKFLOWS.get(prompt_id)
