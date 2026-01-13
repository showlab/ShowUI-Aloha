#!/usr/bin/env python3
"""
End-to-end test runner:
1) Start the server (app_server.py)
2) Start the client (app_client.py)
3) Call the client to interact with the server

Usage:
  python scripts/aloha_run.py --task "open settings"

Options allow overriding ports, timeouts, and steps. Logs are written to logs/.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from typing import Optional, Tuple
import logging
from pathlib import Path

# Configure logging at import time so it's available throughout the module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


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
        log.info(f"Waiting for ready: {code}")
        if code and 200 <= code < 500:  # any concrete response from app indicates readiness
            return True
        time.sleep(interval_s)
    return False


def start_process(name: str, args: list[str], log_path: str) -> subprocess.Popen:
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


def terminate_process(proc: subprocess.Popen, name: str, grace_s: float = 5.0) -> None:
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

def load_prompt_json() -> Optional[dict]:
    try:
        here = Path(__file__).resolve()
    except NameError:
        # __file__ may not exist in some run environments; just skip
        return None

    grandparent = here.parent.parent
    prompt_path = grandparent / "prompt.json"
    if not prompt_path.exists():
        return None
    try:
        with prompt_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return None
    except Exception as e:
        log.warning("Failed to parse %s: %s", prompt_path, e)
        return None
    
def find_trace_json(task_name: str) -> Optional[str]:
    """Find trace file for given task name under ../trace_data."""
    here = Path(__file__).resolve()
    trace_dir = here.parent.parent / "trace_data"
    candidates = [
        trace_dir / f"{task_name}.json",
        trace_dir / f"{task_name}_trace.json",
    ]
    for path in candidates:
        if path.exists():
            return path.stem
    return None  

def main() -> int:
    parser = argparse.ArgumentParser(description="E2E test for Aloha Act server+client")
    parser.add_argument("--server-port", type=int, default=7887)
    parser.add_argument("--client-port", type=int, default=7888)
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("--trace-id", type=str, default="example_trace")
    parser.add_argument("--selected-screen", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--ready-timeout", type=int, default=60, help="Seconds to wait for app readiness")
    parser.add_argument("--task-timeout", type=int, default=600, help="Overall timeout to wait for task completion")
    parser.add_argument("--stop-after-seconds", type=int, default=None, help="Optional: force stop after N seconds")
    args = parser.parse_args()
    prompt = load_prompt_json()
    if prompt is not None:
        # Expecting a dict with keys: "task" (str) and "trace" (str)
        task_from_prompt = prompt.get("task")
        trace_from_prompt = prompt.get("trace")
        if isinstance(task_from_prompt, str) and task_from_prompt.strip():
            log.info("Using task from prompt.json")
            args.task = task_from_prompt
        if isinstance(trace_from_prompt, str) and trace_from_prompt.strip():
            log.info("Using trace_id from prompt.json")
            args.trace_id = trace_from_prompt
    else:
        log.info("prompt.json not found; using CLI/default values")

    # Locate trace file based on task name
    current_dir = Path(__file__).resolve().parent
    trace_name = find_trace_json(args.trace_id)
    if trace_name:
        log.info(f"Found trace file: {trace_name}.json")
        args.trace_id = trace_name
    else:
        log.warning(f"No trace file found for task '{args.trace_id}' in trace_data folder.")

    task_str = args.task
    if not task_str:
        prompt_path = os.path.join(os.getcwd(), "prompt.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                task_str = content
                log.info(f"[e2e] Loaded task from prompt.txt: {task_str[:100]}...")
            else:
                log.warning("[e2e] prompt.txt is empty; using default task.")
                task_str = "Follow the trace and complete the task."
        else:
            log.warning("[e2e] prompt.txt not found; using default task.")
            task_str = "Follow the trace and complete the task."
    # ===================================

    logs_dir = os.path.join("logs")
    mkdir_p(logs_dir)

    server_url = f"http://127.0.0.1:{args.server_port}"
    client_url = f"http://127.0.0.1:{args.client_port}"

    server_proc = start_process(
        "server",
        ["app_server.py"],
        os.path.join(logs_dir, "server_e2e.log"),
    )
    log.info("[e2e] Launched server pid=%s at %s", server_proc.pid, server_url)

    try:
        if not wait_for_ready(f"{server_url}/", method="GET", timeout_s=args.ready_timeout):
            log.error("[e2e] Server did not become ready in time. See logs/server_e2e.log")
            return 1

        client_log_path = os.path.join(logs_dir, "client_e2e.log")
        client_proc = start_process(
            "client",
            ["app_client.py", "--max_steps", str(args.max_steps)],
            client_log_path,
        )
        log.info("[e2e] Launched client pid=%s at %s", client_proc.pid, client_url)

        if not wait_for_ready(f"{client_url}/stop", method="POST", timeout_s=args.ready_timeout):
            log.error("[e2e] Client did not become ready in time. See logs/client_e2e.log")
            return 1

        run_payload = {
            "task": task_str,  # <-- use resolved task here
            "selected_screen": args.selected_screen,
            "trace_id": args.trace_id,
            "max_steps": args.max_steps,
            "server_url": f"{server_url}/generate_action",
        }
        code, body = http_request("POST", f"{client_url}/run_task", payload=run_payload, timeout=10)
        log.info("[e2e] POST /run_task -> %s\n%s", code, body[:200])
        if code < 200 or code >= 300:
            log.error("[e2e] Failed to start task. See logs/client_e2e.log")
            return 1

        if args.stop_after_seconds is not None:
            time.sleep(max(0, args.stop_after_seconds))
            code, body = http_request("POST", f"{client_url}/stop", payload={}, timeout=10)
            log.info("[e2e] POST /stop -> %s\n%s", code, body[:200])
            if code == 400:
                log.warning("[e2e] No active task to stop (likely completed quickly). Proceeding.")

        log.info("[e2e] Waiting for client task completion...")
        deadline = time.time() + args.task_timeout
        finished_marker = "process_input thread finished."
        last_seen_size = 0
        while time.time() < deadline:
            try:
                if os.path.exists(client_log_path):
                    cur_size = os.path.getsize(client_log_path)
                    if cur_size != last_seen_size:
                        last_seen_size = cur_size
                        with open(client_log_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if finished_marker in content:
                            log.info("[e2e] Detected client completion.")
                            break
            except Exception:
                pass
            if client_proc.poll() is not None:
                log.error("[e2e] Client process exited before completion marker. See client logs.")
                break
            time.sleep(0.5)

        log.info("[e2e] Done. Inspect logs/server_e2e.log and logs/client_e2e.log for details.")
        return 0
    finally:
        terminate_process(server_proc, "server")
        try:
            if 'client_proc' in locals():
                terminate_process(client_proc, "client")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

