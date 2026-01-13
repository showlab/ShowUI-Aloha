#!/usr/bin/env python3
"""
Gradio-based end-to-end demo that launches both the server and client,
lets you trigger a run task via the client, and visualizes logs for both.

Usage:
  python scripts/demo_e2e.py

Notes:
  - This mirrors the behavior of scripts/e2e_quick_test.py but exposes
    controls and live logs via a Gradio UI.
  - By default, the server binds to 7887 and the client to 7888.
  - Logs are written under logs/server_demo.log and logs/client_demo.log.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import threading
import urllib.request
import urllib.error
from typing import Optional, Tuple

import gradio as gr


# ----------------------------
# Utilities
# ----------------------------


def mkdir_p(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def http_request(method: str, url: str, payload: Optional[dict] = None, timeout: float = 5.0) -> Tuple[int, str]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            return status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body
    except Exception as e:
        return 0, str(e)


def wait_for_ready(url: str, method: str = "GET", payload: Optional[dict] = None, timeout_s: int = 60, interval_s: float = 0.5) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, _ = http_request(method, url, payload=payload, timeout=2.0)
        if code and 200 <= code < 500:
            return True
        time.sleep(interval_s)
    return False


def start_process(args: list[str], log_path: str) -> subprocess.Popen:
    mkdir_p(os.path.dirname(log_path) or ".")
    log_file = open(log_path, "w", buffering=1)
    proc = subprocess.Popen(
        [sys.executable, *args],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
        text=True,
    )
    return proc


def terminate_process(proc: Optional[subprocess.Popen], grace_s: float = 5.0) -> None:
    if not proc:
        return
    if proc.poll() is not None:
        return
    try:
        if sys.platform.startswith("win"):
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        t0 = time.time()
        while proc.poll() is None and (time.time() - t0) < grace_s:
            time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass


def tail_file(path: str, max_lines: int = 500) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except FileNotFoundError:
        return "(log file not found)"
    except Exception as e:
        return f"(error reading log: {e})"


# ----------------------------
# Runtime state (guarded via simple locks)
# ----------------------------


class RuntimeState:
    def __init__(self) -> None:
        self.server_proc: Optional[subprocess.Popen] = None
        self.client_proc: Optional[subprocess.Popen] = None
        self.server_port: int = 7887
        self.client_port: int = 7888
        self.server_log_path: str = os.path.join("logs", "server_demo.log")
        self.client_log_path: str = os.path.join("logs", "client_demo.log")
        self._lock = threading.Lock()

    def set_ports(self, server_port: int, client_port: int) -> None:
        with self._lock:
            self.server_port = server_port
            self.client_port = client_port

    def is_server_running(self) -> bool:
        return self.server_proc is not None and self.server_proc.poll() is None

    def is_client_running(self) -> bool:
        return self.client_proc is not None and self.client_proc.poll() is None


STATE = RuntimeState()


# ----------------------------
# Actions used by Gradio callbacks
# ----------------------------


def launch_server(server_port: int) -> str:
    STATE.set_ports(server_port, STATE.client_port)
    if STATE.is_server_running():
        return f"Server already running on {server_port} (pid={STATE.server_proc.pid})."

    # Start server
    STATE.server_proc = start_process(["app_server.py"], STATE.server_log_path)
    server_url = f"http://127.0.0.1:{server_port}"
    ok = wait_for_ready(f"{server_url}/", method="GET", timeout_s=60)
    if ok:
        return f"Server ready at {server_url} (pid={STATE.server_proc.pid})."
    return "Server failed to become ready. Check logs/server_demo.log."


def launch_client(client_port: int, max_steps: int) -> str:
    STATE.set_ports(STATE.server_port, client_port)
    if STATE.is_client_running():
        return f"Client already running on {client_port} (pid={STATE.client_proc.pid})."

    # Start client with desired max_steps
    STATE.client_proc = start_process(["app_client.py", "--max_steps", str(max_steps)], STATE.client_log_path)
    client_url = f"http://127.0.0.1:{client_port}"
    ok = wait_for_ready(f"{client_url}/stop", method="POST", timeout_s=60)
    if ok:
        return f"Client ready at {client_url} (pid={STATE.client_proc.pid})."
    return "Client failed to become ready. Check logs/client_demo.log."


def start_task(task: str, trace_id: str, selected_screen: int, max_steps: int) -> str:
    if not STATE.is_client_running():
        return "Client is not running. Launch client first."

    server_url = f"http://127.0.0.1:{STATE.server_port}/generate_action"
    client_url = f"http://127.0.0.1:{STATE.client_port}"
    payload = {
        "task": task,
        "selected_screen": int(selected_screen),
        "trace_id": trace_id,
        "max_steps": int(max_steps),
        "server_url": server_url,
    }
    code, body = http_request("POST", f"{client_url}/run_task", payload=payload, timeout=15)
    return f"POST /run_task -> {code}\n{body[:500]}"


def stop_task() -> str:
    if not STATE.is_client_running():
        return "Client is not running. Nothing to stop."
    client_url = f"http://127.0.0.1:{STATE.client_port}"
    code, body = http_request("POST", f"{client_url}/stop", payload={}, timeout=10)
    return f"POST /stop -> {code}\n{body[:500]}"


def shutdown_all() -> str:
    terminate_process(STATE.client_proc)
    terminate_process(STATE.server_proc)
    STATE.client_proc = None
    STATE.server_proc = None
    return "Shutdown signals sent to server and client."


def refresh_logs() -> tuple[str, str]:
    return tail_file(STATE.server_log_path, max_lines=400), tail_file(STATE.client_log_path, max_lines=400)


# ----------------------------
# Gradio UI
# ----------------------------


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Aloha Act E2E Demo") as demo:
        gr.Markdown("""
        # Aloha Act E2E Demo
        - Launch the server and client.
        - Start a task through the client (which calls the server's action endpoint).
        - Watch logs from both sides update live.
        """)

        with gr.Row():
            with gr.Column():
                # Note: app_server.py and app_client.py currently bind to fixed ports (7887/7888)
                # These are displayed for clarity and used to build URLs.
                server_port = gr.Number(value=7887, label="Server Port (fixed)", precision=0, interactive=False)
                client_port = gr.Number(value=7888, label="Client Port (fixed)", precision=0, interactive=False)
                max_steps = gr.Number(value=10, label="Max Steps", precision=0)
                task = gr.Textbox(value="check my mac's information", label="Task")
                trace_id = gr.Textbox(value="demo_trace", label="Trace ID")
                selected_screen = gr.Number(value=0, label="Selected Screen", precision=0)

                with gr.Row():
                    btn_launch_server = gr.Button("Launch Server")
                    btn_launch_client = gr.Button("Launch Client")
                with gr.Row():
                    btn_start = gr.Button("Start Task")
                    btn_stop = gr.Button("Stop Task")
                btn_shutdown = gr.Button("Shutdown All")
                status = gr.Textbox(label="Status", interactive=False)

            with gr.Column():
                server_log = gr.Textbox(label="Server Log", lines=22, interactive=False)
                client_log = gr.Textbox(label="Client Log", lines=22, interactive=False)

        # Wire actions
        btn_launch_server.click(fn=launch_server, inputs=[server_port], outputs=[status])
        btn_launch_client.click(fn=launch_client, inputs=[client_port, max_steps], outputs=[status])
        btn_start.click(fn=start_task, inputs=[task, trace_id, selected_screen, max_steps], outputs=[status])
        btn_stop.click(fn=stop_task, outputs=[status])
        btn_shutdown.click(fn=shutdown_all, outputs=[status])

        # Periodic log refresh (Gradio v5+ API)
        _timer = gr.Timer(1.0)
        _timer.tick(refresh_logs, outputs=[server_log, client_log])

    return demo


def main() -> None:
    demo = build_ui()
    # Share=False keeps local; adjust as needed
    demo.launch(server_name="0.0.0.0", server_port=7890, show_error=True)


if __name__ == "__main__":
    main()
