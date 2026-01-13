import argparse
import time
import json
import platform
import uuid
import base64
import datetime
import logging
from datetime import datetime, timedelta, timezone

from ui_aloha.execute.executor.aloha_executor import AlohaExecutor
from ui_aloha.execute.utils.server_connection import is_image_path, send_inference_request
from ui_aloha.execute.gui_parser.gui_capture import capture_screenshot


utc_plus_8 = timezone(timedelta(hours=8))
log = logging.getLogger(__name__)


def simple_sampling_loop(
    task: str,
    action_history: list[dict] = None,
    selected_screen: int = 0,
    trace_id: str = None,
    server_url: str = "http://localhost:7887/generate_action",
    max_steps: int = 20,
):
    """
    Synchronous sampling loop for assistant/tool interactions.
    """
    # Initialize action_history if it's None
    if action_history is None:
        action_history = []

    executor = AlohaExecutor(
        selected_screen=selected_screen,
    )

    timestamp = datetime.now(utc_plus_8).strftime("%m%d-%H%M%S")

    step_count = 1
    unique_task_id = f"{timestamp}_tid_{trace_id}_{str(uuid.uuid4())[:6]}"

    log.info("[simple_sampling_loop] starting task: %s unique_task_id: %s", task, unique_task_id)


    while step_count < max_steps:
        
        log.info("step_count: %s", step_count)

        # Pause briefly so we don't spam screenshots
        time.sleep(1)

        sc_path = capture_screenshot(selected_screen=selected_screen)
        
        # yield {"role": "assistant", "content": "screenshot", "type": "action", "action_type": "screenshot"}

        if is_image_path(sc_path):
            # yield {"role": "assistant", "content": sc_path, "type": "image", "action_type": "screenshot"} 
            with open(sc_path, "rb") as image_file:
                sc_base64 = base64.b64encode(image_file.read()).decode('utf-8')
            yield {"role": "assistant", "content": sc_base64, "type": "image_base64", "action_type": "screenshot"} 

        # Payload expected by app_server.generate_action:
        payload = {
            "task_id": unique_task_id,
            "screenshot_path": sc_path,
            "query": task,
            "action_history": action_history,
            "trace_name": trace_id,
        }

        # Send request to  Run server
        infer_server_response = send_inference_request(payload, server_url)
        # infer_server_response = {
        #     'status': 'success',
        #     'generated_plan': plan_details,
        #     'generated_action': action,
        #     'todo_md': todo_md_content,
        #     'milestones': milestones,
        #     'current_step': current_step,
        # }

        if infer_server_response is None:
            log.error("No response from Run server. Exiting.")
            yield {"role": "assistant", "content": "No response from  Run server. Exiting.", "type": "error"}
            action_history = []
            break

        try:
            step_plan = infer_server_response["generated_plan"]
            step_plan_observation = step_plan["observation"]
            step_plan_reasoning = step_plan["reasoning"]
            step_plan_info = step_plan["step_info"]
            step_action = infer_server_response["generated_action"]["content"]
            step_traj_idx = infer_server_response["current_traj_step"]

        except Exception as e:
            log.error("Error parsing generated_action content: %s", e)
            yield {"role": "assistant", "content": "Error parsing response from  Run server. Exiting.", "type": "error"}
            break
        
        chat_visable_content = f"{step_plan_observation}{step_plan_reasoning}"
        yield {"role": "assistant", "content": step_plan_observation, "type": "text"}
        yield {"role": "assistant", "content": step_plan_reasoning, "type": "text"}

        if step_action.get("action") == "STOP":
            final_sc_path = capture_screenshot(selected_screen=selected_screen)

            with open(final_sc_path, "rb") as image_file:
                final_sc_base64 = base64.b64encode(image_file.read()).decode('utf-8')
            yield {"role": "assistant", "content": "Task completed. Final screenshot:", "type": "text"}
            yield {"role": "assistant", "content": final_sc_base64, "type": "image_base64", "action_type": "screenshot"} 

            # reset action history
            action_history = []  
            break

        action_history.append(f"Executing guidance trajectory step [{step_traj_idx}]: {{Plan: {step_plan_info}, Action: {step_action}}}\n")

        for exec_message in executor({"role": "assistant", "content": step_action}):
            yield exec_message

        step_count += 1
    
    # reset action history
    action_history = []
