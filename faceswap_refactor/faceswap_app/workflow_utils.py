
import json, copy
from pathlib import Path
from typing import Dict, Any

from .exceptions import ComfyUIError
from .config import WORKFLOW_TEMPLATE_PATH

def _load_template(path: Path = WORKFLOW_TEMPLATE_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise ComfyUIError(f"Workflow template not found: {path}")
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ComfyUIError(f"Invalid workflow JSON: {exc}") from exc

def load_and_patch_workflow(video_filename: str, image_filename: str, output_prefix: str, template_path: Path = WORKFLOW_TEMPLATE_PATH) -> Dict[str, Any]:
    workflow = copy.deepcopy(_load_template(template_path))

    def _replace(val: str) -> str:
        return (
            val.replace("{video_filename}", video_filename)
               .replace("{image_filename}", image_filename)
               .replace("{output_prefix}", output_prefix)
        )

    for node in workflow.get("nodes", []):
        params = node.get("params", {})
        for key, value in list(params.items()):
            if isinstance(value, str):
                params[key] = _replace(value)

    meta = workflow.setdefault("_meta", {})
    meta["generated_by"] = "faceswap_app"
    meta["output_prefix"] = output_prefix
    return workflow

def build_node_title_map(workflow: Dict[str, Any]) -> Dict[int, str]:
    return {
        int(node_id): node.get("_meta", {}).get("title", f"Node {node_id}")
        for node_id, node in enumerate(workflow.get("nodes", []))
    }
