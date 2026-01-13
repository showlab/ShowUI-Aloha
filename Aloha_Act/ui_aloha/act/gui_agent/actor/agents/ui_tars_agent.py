import re
import json
from ui_aloha.act.gui_agent.llm.llm_utils import encode_image


# all hosted local models can be used as it
class UITarsAgent:
    def __init__(self, local_cua_model_url="http://localhost:8000/", logger=None):
        self.local_cua_model_url = local_cua_model_url
        self.logger = logger
    
    def execute(self, instruction, screenshot_path, system_prompt, logging_dir):
        """Execute UI-TARS agent action"""
        
        # Prepare inputs
        _ = encode_image(screenshot_path)  # encoded image available for future API call
        prompted_message = self._get_prompt_grounding(instruction)
        
        try:
            # Log the prompts
            if self.logger:
                self.logger.log_text(prompted_message, "actor_uitars_prompt.log", logging_dir)
                self.logger.log_text(system_prompt, "actor_uitars_system.log", logging_dir)
                self.logger.log_json({
                    "instruction": str(instruction),
                    "local_cua_model_url": self.local_cua_model_url
                }, "actor_uitars_request.json", logging_dir)
            
            # TODO: Implement actual UI-TARS API call when model is available
            # For now, return a placeholder action based on instruction
            ui_tars_action = "click(start_box='(200,150)')"
            
            if self.logger:
                self.logger.log_text(ui_tars_action, "actor_uitars_raw_response.log", logging_dir)
            
            # For ui-tars, check if the response indicates completion
            complete_flag = "finished()" in ui_tars_action
            
            # Convert ui-tars action to json format
            action_json = json.loads(convert_ui_tars_action_to_json(ui_tars_action))
            
            # Log the parsed action
            if self.logger:
                self.logger.log_json(action_json, "actor_uitars_parsed_action.json", logging_dir)
            
            return action_json, complete_flag
            
        except Exception as e:
            error_msg = f"Error processing UI-TARS response: {e}"
            if self.logger:
                self.logger.logger.error(error_msg)
                self.logger.log_error(e, {"mode": "ui-tars"}, target_dir=logging_dir)
            
            return {"action": "ERROR", "value": str(e), "position": [0, 0]}, False
    
    @staticmethod
    def _get_prompt_grounding(instruction):
        """Format instruction for UI-TARS - no need to prompt for ui-tars"""
        return f"""{instruction}"""


def convert_ui_tars_action_to_json(action_str: str) -> str:
    """
    Converts an action line such as:
        Action: click(start_box='(153,97)')
    into a JSON string of the form:
      {
        "action": "CLICK",
        "value": null,
        "position": [153, 97]
      }
    """
    
    # Strip leading/trailing whitespace and remove "Action: " prefix if present
    action_str = action_str.strip()
    if action_str.startswith("Action:"):
        action_str = action_str[len("Action:"):].strip()

    # Mappings from old action names to the new action schema
    ACTION_MAP = {
        "click": "CLICK",
        "type": "INPUT",
        "scroll": "SCROLL",
        "wait": "STOP",        # TODO: deal with "wait()"
        "finished": "STOP",
        "call_user": "STOP",
        "hotkey": "HOTKEY",    # We break down the actual key below (Enter, Esc, etc.)
    }

    # Prepare a structure for the final JSON
    # Default to no position and null value
    output_dict = {
        "action": None,
        "value": None,
        "position": None
    }

    # 1) CLICK(...) e.g. click(start_box='(153,97)')
    match_click = re.match(r"^click\(start_box='\(?(\d+),\s*(\d+)\)?'\)$", action_str)
    if match_click:
        x, y = match_click.groups()
        output_dict["action"] = ACTION_MAP["click"]
        output_dict["position"] = [int(x), int(y)]
        return json.dumps(output_dict)

    # 2) HOTKEY(...) e.g. hotkey(key='Enter')
    match_hotkey = re.match(r"^hotkey\(key='([^']+)'\)$", action_str)
    if match_hotkey:
        key = match_hotkey.group(1).lower()
        if key == "enter":
            output_dict["action"] = "ENTER"
        elif key == "esc":
            output_dict["action"] = "ESC"
        else:
            # Otherwise treat it as some generic hotkey
            output_dict["action"] = ACTION_MAP["hotkey"]
            output_dict["value"] = key
        return json.dumps(output_dict)

    # 3) TYPE(...) e.g. type(content='some text')
    match_type = re.match(r"^type\(content='([^']*)'\)$", action_str)
    if match_type:
        typed_content = match_type.group(1)
        output_dict["action"] = ACTION_MAP["type"]
        output_dict["value"] = typed_content
        # If you want a position (x,y) you need it in your string. Otherwise it's omitted.
        return json.dumps(output_dict)

    # 4) SCROLL(...) e.g. scroll(start_box='(153,97)', direction='down')
    #    or scroll(start_box='...', direction='down')
    match_scroll = re.match(
        r"^scroll\(start_box='[^']*'\s*,\s*direction='(down|up|left|right)'\)$",
        action_str
    )
    if match_scroll:
        direction = match_scroll.group(1)
        output_dict["action"] = ACTION_MAP["scroll"]
        output_dict["value"] = direction
        return json.dumps(output_dict)

    # 5) WAIT() or FINISHED() or CALL_USER() etc.
    if action_str in ["wait()", "finished()", "call_user()"]:
        base_action = action_str.replace("()", "")
        if base_action in ACTION_MAP:
            output_dict["action"] = ACTION_MAP[base_action]
        else:
            output_dict["action"] = "STOP"
        return json.dumps(output_dict)

    # If none of the above patterns matched, you can decide how to handle
    # unknown or unexpected action lines:
    output_dict["action"] = "STOP"
    return json.dumps(output_dict)