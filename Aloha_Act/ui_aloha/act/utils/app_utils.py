import os
import json
import uuid
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from ui_aloha.act.gui_agent.actor.ui_aloha_actor import AlohaActor
from ui_aloha.act.gui_agent.planner.ui_aloha_planner import AlohaPlanner
from ui_aloha.act.gui_agent.planner.trajectory_manager import TrajectoryManager


def validate_request(data: Dict) -> bool:
    """Minimal validation for incoming request data.

    Only `screenshot` and `query` are required; `task_id` is optional and will
    be generated server-side when missing.
    """
    required_fields = ["screenshot", "query"]
    return all(field in data for field in required_fields)

def setup_logging_directory(task_id: str) -> str:
    """Set up logging directory for the current request."""
    timestamp = datetime.now().strftime("%m%d-%H-%M-%S")
    log_dir = os.path.join("./logs", f"{task_id}_{timestamp}")
    # log_dir = os.path.join("./logs", f"{task_id}")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def prepare_response(loop_result: Dict) -> Dict:
    """Prepare the API response from the loop result.

    The shape is stable for client integration and visualization.
    """
    return {
        "status": "success",
        "generated_plan": loop_result.get("plan_details", {}),
        "generated_action": loop_result.get("action", {}),
        "current_traj_step": loop_result.get("curr_traj_step", 1),
        "complete_flag": loop_result.get("complete_flag", False),
    }
    

def initialize_agent_components(config, trace_dir, api_keys):
    """Initialize and return all agent components from config/env."""
    planner_model = config.get("planner_model", "gpt-4o")
    actor_model = config.get("actor_model", "oai-operator")
    os_name = config.get("os_name", "windows")
    
    return {
        "trajectory_manager": TrajectoryManager(base_path=trace_dir),
        "planner": AlohaPlanner(model=planner_model, os_name=os_name, api_keys=api_keys),
        "actor": AlohaActor(model=actor_model, os_name=os_name, api_keys=api_keys),
    }


def save_screenshot(screenshot: str, save_screenshot_dir: str = "./cache") -> str:
    """Persist a base64-encoded screenshot to disk and return its path."""
    os.makedirs(save_screenshot_dir, exist_ok=True)
    utc_plus_8 = timezone(timedelta(hours=8))
    current_time = datetime.now(utc_plus_8).strftime("%Y%m%d_%H%M%S")

    screenshot_path = os.path.join(
        save_screenshot_dir, f"screenshot_{current_time}_{uuid.uuid4()}.png"
    )
    with open(screenshot_path, "wb") as f:
        f.write(base64.b64decode(screenshot))
    return screenshot_path


def load_api_keys(json_path: str = "./config/api_keys.json") -> Dict[str, str]:
    """Load API keys from environment and optional JSON file (git-ignored)."""
    keys: Dict[str, str] = {}
    
    try:
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                file_keys = json.load(f) or {}
            if isinstance(file_keys, dict):
                for k, v in file_keys.items():
                    keys.setdefault(k, v)
    except Exception as e:
        logging.getLogger("aloha.app").warning(f"Could not read API keys file: {e}")

    for export_key in [
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "CLAUDE_API_KEY",
        "OPERATOR_OPENAI_API_KEY",
    ]:
        if export_key in keys and not os.getenv(export_key):
            os.environ[export_key] = keys[export_key]

    return keys
