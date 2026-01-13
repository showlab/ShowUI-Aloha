import json
from typing import Tuple
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from ui_aloha.act.utils.path_utils import prompt_templates_path
from openai import OpenAI

from ui_aloha.act.gui_agent.llm.llm_utils import encode_image


class OAIOperatorAgent:
    def __init__(self, api_key, local_cua_model_url: str = "", logger=None):
        self.logger = logger
        self.client = OpenAI(api_key=api_key) if api_key else None

        # Action type conversion mapping
        self.action_type_convert = {
            "click": "CLICK",
            "double_click": "DOUBLE_CLICK",
            "move": "MOVE",
            "scroll": "SCROLL",
            "wait": "WAIT",
            "type": "INPUT",
            "drag": "DRAG",
            "keypress": "KEY",
            "screenshot": "SCREENSHOT",
        }

        # Templates for user prompt
        templates_dir = prompt_templates_path("actor")
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @staticmethod
    def _normalize_environment(os_name: str) -> str:
        """Map incoming OS names to the supported computer-use environments."""
        if not os_name:
            return "windows"
        normalized = os_name.strip().lower()
        mapping = {
            "win": "windows",
            "win32": "windows",
            "macos": "mac",
            "osx": "mac",
            "darwin": "mac",
            "ubuntu": "linux",
        }
        translated = mapping.get(normalized, normalized)
        allowed = {"windows", "mac", "linux", "browser"}
        return translated if translated in allowed else "windows"

    def execute(self, instruction, screenshot_path: str, os_name: str, system_prompt: str, logging_dir: str) -> Tuple[dict, bool]:
        """Execute OAI Operator via OpenAI Responses API with computer-use tool."""
        if not self.client:
            msg = "OpenAI client not initialized; missing API key"
            if self.logger:
                self.logger.logger.error(msg)
            return {"action": "ERROR", "value": msg, "position": [0, 0]}, False

        # DISPLAY_WIDTH = 1920
        # DISPLAY_HEIGHT = 1080
        DISPLAY_WIDTH, DISPLAY_HEIGHT = Image.open(screenshot_path).size
        ENVIRONMENT = self._normalize_environment(os_name)
        if self.logger and os_name != ENVIRONMENT:
            self.logger.logger.info(f"Normalized os_name '{os_name}' to '{ENVIRONMENT}' for computer-use tool")
        if self.logger:
            self.logger.logger.info(f"DISPLAY_WIDTH: {DISPLAY_WIDTH}, DISPLAY_HEIGHT: {DISPLAY_HEIGHT}, ENVIRONMENT: {ENVIRONMENT}")

        # Render user text
        try:
            user_text = self._jinja_env.get_template("user_cua.txt").render(task=instruction)
        except Exception:
            user_text = str(instruction)

        screenshot_b64 = encode_image(screenshot_path)

        if self.logger:
            self.logger.log_text(system_prompt + "\n" + user_text, "actor_oai_operator_request.log", logging_dir)

        try:
            response = self.client.responses.create(
                model="computer-use-preview",
                tools=[
                    {
                        "type": "computer_use_preview",
                        "display_width": DISPLAY_WIDTH,
                        "display_height": DISPLAY_HEIGHT,
                        "environment": ENVIRONMENT,  # "browser", "mac", "windows", "linux"

                    }
                ],
                input=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": user_text},
                            {"type": "input_image", "image_url": f"data:image/png;base64,{screenshot_b64}"},
                        ],
                    },
                ],
                reasoning={"generate_summary": "concise"},
                truncation="auto",
                tool_choice="required",
                temperature=0.0,
            )

            action_json = self._parse_response(response, user_text)
            complete_flag = action_json.get("action") == "STOP"

            if self.logger:
                self.logger.log_json({"response": str(response)}, "actor_oai_operator_raw_response.json", logging_dir)
                self.logger.log_json(action_json, "actor_oai_operator_parsed_action.json", logging_dir)

            return action_json, complete_flag

        except Exception as e:
            error_msg = f"Error processing oai-operator response: {e}"
            if self.logger:
                self.logger.logger.error(error_msg)
                self.logger.log_error(e, {"mode": "oai-operator"}, target_dir=logging_dir)
            return {"action": "ERROR", "value": str(e), "position": [0, 0]}, False

    def _parse_response(self, response, user_text: str) -> dict:
        """Parse OpenAI computer-use response into standardized action format."""
        action_json: dict = {}
        outputs = getattr(response, "output", [])
        computer_call_found = False

        for item in outputs or []:
            item_type = getattr(item, "type", None)
            if item_type == "computer_call":
                computer_call_found = True
                action = getattr(item, "action", None)
                action_type = getattr(action, "type", None)

                if action_type in self.action_type_convert:
                    if action_type in ["click", "move", "double_click"]:
                        x = getattr(action, "x", 0)
                        y = getattr(action, "y", 0)

                        # Distinguish left vs right click (default to left)
                        if action_type == "click":
                            button = getattr(action, "button", "left")
                            if str(button).lower() == "right":
                                action_name = "RIGHT_CLICK"
                            else:
                                action_name = "CLICK"
                        elif action_type == "double_click":
                            action_name = "DOUBLE_CLICK"
                        else:
                            # move
                            action_name = "MOVE"

                        action_json = {
                            "action": action_name,
                            "value": "",
                            "position": [x, y],
                        }
                    elif action_type == "keypress":
                        keys = getattr(action, "keys", "")

                        # Normalize keys into a list of tokens for classification.
                        if isinstance(keys, (list, tuple)):
                           tokens = [str(k).strip() for k in keys if str(k).strip()]
                        else:
                            raw = str(keys)
                            # Split on '+' to honor chords like "CTRL+S", otherwise treat as single token
                            tokens = [t.strip() for t in raw.split("+")] if "+" in raw else [raw.strip()]

                        # Define modifier/special sets (lowercased for checks)
                        modifiers = {"ctrl", "control", "shift", "alt", "meta", "cmd", "command", "win", "super"}
                        specials  = {}

                       # Helper to decide if a token represents a single printable char
                        def is_printable_char(tok: str) -> bool:
                            # Allow single visible character like 'a', '7', ':', etc.
                            return len(tok) == 1 and tok.isprintable()

                        lower_tokens = [t.lower() for t in tokens]

                        has_modifier_or_special = any(
                            (t in modifiers) or (t in specials) for t in lower_tokens
                        )
                        all_printable_chars = all(is_printable_char(t) for t in tokens)

                        if tokens and not has_modifier_or_special and all_printable_chars:
                            # Aggressive merge into a single INPUT (typing) action.
                            # Convert "space" names were filtered above; if upstream ever sends " " as token it stays.
                            typed = "".join(tokens)
                            action_json = {
                                "action": "INPUT",
                                "value": typed,
                                "position": "",
                            }
                        else:
                            # Fall back to a proper chord for any modifier/special presence.
                           # Normalize to executor's expectations: "ctrl+s" etc. (executor splits on '+')
                            # Map a lone 'space' to a literal space so typing still works if needed.
                            if len(tokens) == 1 and lower_tokens[0] == "space":
                                value_norm = " "
                                action_json = {
                                    "action": "INPUT",
                                    "value": value_norm,
                                    "position": "",
                                }
                            else:
                                parts = []
                                for t in tokens:
                                    parts.append(t.lower())
                                value_norm = "+".join(parts)
                                action_json = {
                                    "action": self.action_type_convert[action_type],  # => "key"
                                    "value": value_norm,
                                    "position": "",
                                }
                    elif action_type == "scroll":
                        scroll_x = getattr(action, "scroll_x", 0)
                        scroll_y = getattr(action, "scroll_y", 0)
                        direction = "down" if scroll_y > 0 else "up"
                        x = getattr(action, "x", 0)
                        y = getattr(action, "y", 0)
                        action_json = {
                            "action": self.action_type_convert[action_type],
                            "direction": direction,
                            "position": [x, y],
                            "value": [scroll_x, scroll_y],
                        }
                    elif action_type == "wait":
                        action_json = {
                            "action": self.action_type_convert[action_type],
                            "value": "",
                            "position": "",
                        }
                    elif action_type == "type":
                        text = getattr(action, "text", "")
                        action_json = {
                            "action": self.action_type_convert[action_type],
                            "value": text,
                            "position": "",
                        }
                    elif action_type == "drag":
                        # Collect the sequence of points that define the drag gesture
                        points = []
                        seq = getattr(action, "path", None) or getattr(action, "paths", None) or []
                        for p in seq:
                            px = getattr(p, "x", None)
                            py = getattr(p, "y", None)
                            if px is not None and py is not None:
                                points.append([px, py])

                        if not points and hasattr(action, "x") and hasattr(action, "y"):
                            points = [[getattr(action, "x", 0), getattr(action, "y", 0)]]

                        action_json = {
                            "action": "DRAG",
                            "start": points[0],       
                            "end": points[-1]      
                        }
                    else:
                        if self.logger:
                            self.logger.logger.info(f"oai_operator: unsupported action type {action_type}")

            elif item_type == "output_text":
                text = getattr(item, "text", "")
                if self.logger:
                    self.logger.logger.info(
                        f"oai_operator: output_text={text}. Check planner prompt for: {user_text}"
                    )
                last_output_text = text
            elif item_type == "reasoning":
                # ignore
                pass

        if not computer_call_found:
            if self.logger:
                self.logger.logger.warning("oai_operator: no computer_call found in response output")
            action_json = {
                "action": "ERROR",
                "value": last_output_text if 'last_output_text' in locals() and last_output_text else "No computer_call found in output. Re-run the planning.",
                "position": [0, 0],
            }
        return action_json
