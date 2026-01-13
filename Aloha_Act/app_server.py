import os
from datetime import datetime
from typing import Any, Dict

from flask import Flask, jsonify, request

from config import config

from ui_aloha.act.loop.ui_aloha_loop import ui_aloha_loop
from ui_aloha.act.utils.app_utils import (
    initialize_agent_components,
    load_api_keys,
    prepare_response,
    setup_logging_directory,
    validate_request,
)

# Initialize Flask app
app = Flask(__name__)

# Load configuration and ensure folders exist
log_root = config.get("log_dir", "./logs")
trace_dir = config.get("trace_dir", "./trace_data")
os.makedirs(log_root, exist_ok=True)
os.makedirs(trace_dir, exist_ok=True)

# Initialize agent components
api_keys = load_api_keys("./config/api_keys.json")
agent_components = initialize_agent_components(config, trace_dir, api_keys)


@app.route("/")
def home() -> str:
    """Health check endpoint to verify server is running."""
    return "Aloha API server is running"


@app.route("/generate_action", methods=["POST"])
def generate_action():
    """Generate the next action given a task, screenshot, and optional history."""
    data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}

    if not validate_request(data):
        return jsonify({"error": "Missing required fields: screenshot, query"}), 400

    # Extract fields with sensible defaults
    trace_name = data.get(
        "trace_name",
        "example_trace",
    )
    task_id = data.get("task_id", f"task_{datetime.now().strftime('%m%d-%H-%M-%S')}")
    screenshot = data.get("screenshot")
    query = data.get("query")
    action_history = data.get("action_history", [])

    # Set up a per-request logging directory under log root
    log_dir = setup_logging_directory(task_id)

    # try:
    
    loop_result = ui_aloha_loop(
        trajectory_manager=agent_components["trajectory_manager"],
        planner=agent_components["planner"],
        actor=agent_components["actor"],
        task_id=task_id,
        query=query,
        screenshot=screenshot,
        action_history=action_history,
        trace_name=trace_name,
        log_dir=log_dir,
    )

    return jsonify(prepare_response(loop_result))

    # except Exception as e:
    #     return jsonify({"error": f"Error processing request: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7887, debug=True)
