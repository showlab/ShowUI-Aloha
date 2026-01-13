from typing import Any

import argparse
import time
import threading
import platform
import os
import logging

from flask import Flask, request, jsonify

from ui_aloha.execute.executor.aloha_executor import AlohaExecutor
from ui_aloha.execute.sampling_loop import simple_sampling_loop


class SharedState:
    def __init__(self, args):
        self.args = args
        self.task = getattr(args, 'task', "")
        self.selected_screen = args.selected_screen
        self.trace_id = args.trace_id
        self.server_url = args.server_url
        self.max_steps = getattr(args, 'max_steps', 50)

        self.is_processing = False
        self.should_stop = False
        self.stop_event = threading.Event()
        self.processing_thread: threading.Thread | None = None


shared_state: SharedState | None = None

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


def process_input():
    global shared_state
    assert shared_state is not None
    logging.info("process_input thread started.")
    shared_state.is_processing = True
    shared_state.should_stop = False
    shared_state.stop_event.clear()

    try:
        sampling_loop = simple_sampling_loop(
            task=shared_state.task,
            selected_screen=shared_state.selected_screen,
            trace_id=shared_state.trace_id,
            server_url=shared_state.server_url,
            max_steps=shared_state.max_steps,
        )

        for loop_msg in sampling_loop:
            if shared_state.should_stop or shared_state.stop_event.is_set():
                break

            # Log minimal progress for visibility
            try:
                msg_type = loop_msg.get("type")
                content_preview = str(loop_msg.get("content"))[:100]
                logging.info(f"[loop_msg] type={msg_type} content={content_preview}")
            except Exception:
                logging.info(f"[loop_msg] {str(loop_msg)[:100]}")

            # light pacing to avoid busy loop in UI
            time.sleep(0.1)

            if shared_state.should_stop or shared_state.stop_event.is_set():
                break

    except Exception as e:
        logging.error(f"Error during task processing: {e}", exc_info=True)
    finally:
        shared_state.is_processing = False
        shared_state.should_stop = False
        shared_state.stop_event.clear()
        logging.info("process_input thread finished.")


@app.route("/run_task", methods=["POST"])
def run_task():
    """Start a background task that chats with the server and executes actions locally."""
    data = request.get_json(silent=True) or {}
    required = ["task"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"status": "error", "message": f"Missing required field(s): {', '.join(missing)}"}), 400

    assert shared_state is not None
    if shared_state.is_processing:
        return jsonify({"status": "error", "message": "A task is already running"}), 409

    # Update runtime parameters if provided
    shared_state.task = data.get("task", shared_state.task)
    shared_state.selected_screen = data.get("selected_screen", shared_state.selected_screen)
    shared_state.trace_id = data.get("trace_id", shared_state.trace_id)
    shared_state.server_url = data.get("server_url", shared_state.server_url)
    shared_state.max_steps = data.get("max_steps", shared_state.max_steps)

    shared_state.stop_event.clear()
    shared_state.processing_thread = threading.Thread(target=process_input, daemon=True)
    shared_state.processing_thread.start()

    return jsonify({"status": "success", "message": "Task started", "task": shared_state.task})


@app.route("/stop", methods=["POST"])
def stop():
    assert shared_state is not None
    if not shared_state.is_processing:
        return jsonify({"status": "error", "message": "No active task to stop"}), 400

    shared_state.should_stop = True
    shared_state.stop_event.set()

    return jsonify({"status": "success", "message": "Stop signal sent"})


def main():
    logging.info("App main() function starting setup.")
    global shared_state
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, default="Following the instructions to complete the task.", help="Task description")
    parser.add_argument("--selected_screen", type=int, default=0, help="Selected screen index")
    parser.add_argument("--trace_id", type=str, default="example_trace", help="Trace ID for the session")
    parser.add_argument(
        "--server_url",
        type=str,
        default="http://127.0.0.1:7887/generate_action",
        help="Action server endpoint",
    )
    parser.add_argument("--max_steps", type=int, default=50)

    args = parser.parse_args()

    shared_state = SharedState(args)
    logging.info("Shared state initialized.")

    port = 7888
    host = "0.0.0.0"
    logging.info(f"Starting Client Flask on {host}:{port}")
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
