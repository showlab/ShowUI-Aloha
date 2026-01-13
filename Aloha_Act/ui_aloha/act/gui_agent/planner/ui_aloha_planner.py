"""Planner component that produces plan JSON from inputs."""

import re
import json
from jinja2 import Environment, FileSystemLoader
from PIL import Image

from ui_aloha.act.utils.path_utils import prompt_templates_path

from ui_aloha.act.gui_agent.llm.run_llm import run_llm
from ui_aloha.act.gui_agent.llm.llm_utils import extract_data

from ui_aloha.act.utils.logger_utils import LoggerUtils


class AlohaPlanner:
    def __init__(
        self,
        model: str, 
        os_name: str = "windows",
        max_tokens: int = 8000,
        selected_screen: int = 0,
        print_usage: bool = False,
        api_keys: dict = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.selected_screen = selected_screen
        self.os_name = os_name

        self.print_usage = print_usage
        self.total_token_usage = 0
        self.total_cost = 0

        self.api_keys = api_keys
        
        # Initialize logger
        self.logger = LoggerUtils(component_name="planner")
        
        # Jinja2 template environment
        templates_dir = prompt_templates_path()
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        

    def __call__(
        self,
        task: str,
        guidance_trajectory: str = "",
        screenshot_path: str | None = None,
        action_history: list | None = None,
        logging_dir: str = ".cache",
    ) -> dict:
        
        # Take a screenshot
        if not screenshot_path:
            raise ValueError("Screenshot path is required in planner")
        

        system_prompt = self._get_system_prompt(
            os_name=self.os_name,
            guidance_trajectory_example=guidance_trajectory,
        )

        # Format action_history into messages
        action_history = action_history or []
        action_history_str = ""
        if action_history:
            for i, action in enumerate(action_history):
                action_history_str += f"step {i+1}: {action}"

        # if self.resize_down_screenshot:
        #     resized_screenshot_path = os.path.join(logging_dir, "resized_screenshot.png")
        #     resized_screenshot_path = self._resize_down_screenshot(screenshot_path, resized_screenshot_path)
        # else:
        #     resized_screenshot_path = screenshot_path

        user_text = self._jinja_env.get_template("planner/user.txt").render(
            task=task,
            guidance_trajectory_example=guidance_trajectory,
            max_history_length=len(action_history),
            action_history_str=action_history_str,
        )

        user_messages = [
            {"role": "user", "content": [
                user_text,
                f"{screenshot_path}",
            ]}
        ]
        
        # Generate response and token usage
        llm_response, token_usage = run_llm(
            messages=user_messages,
            system=system_prompt,
            llm=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            api_keys=self.api_keys,
        )

        if self.print_usage:
            # New run_llm returns a dict {model_name: token_count}
            token_count = (
                sum(token_usage.values()) if isinstance(token_usage, dict) else int(token_usage or 0)
            )
            self.total_token_usage += token_count
            self.total_cost += (token_count * 0.15 / 1000000)  # https://openai.com/api/pricing/
            self.logger.logger.info(f"LLMPlanner total token usage so far: {self.total_token_usage}. Total cost so far: $USD{self.total_cost:.5f}")

        # Log the raw planner response
        self.logger.log_text(llm_response, "planner_raw_response.log", logging_dir)

        try:
            llm_response_json = extract_data(llm_response, data_type="json")  # Extract data
        except Exception as e:
            error_msg = f"Error extracting data from LLMPlanner response: {e}, llm_response: {llm_response}"
            self.logger.logger.error(error_msg)
            self.logger.log_error(e, {"response": llm_response}, target_dir=logging_dir)
            llm_response_json = str(llm_response)

        # Parse JSON defensively
        try:
            parsed_dict = json.loads(llm_response_json)
            if not isinstance(parsed_dict, dict):
                raise ValueError("Planner output is not a JSON object")
        except Exception as e:
            self.logger.logger.error(f"Failed to parse planner JSON: {e}")
            self.logger.log_error(e, {"raw": llm_response_json}, target_dir=logging_dir)
            parsed_dict = {}
        
        current_step_raw = parsed_dict.get('Current Step in Guidance Trajectory')
        if isinstance(current_step_raw, str) and current_step_raw.strip():
            try:
                current_step_response = self._escape_quotes_in_tuple_string(current_step_raw)
                current_step_tuple = self._safer_parse_step_response(current_step_response)
                parsed_dict['Current Step'] = current_step_tuple[0]
                parsed_dict['Current Step Explanation'] = current_step_tuple[1]
            except Exception as e:
                parsed_dict['Current Step'] = 1
                parsed_dict['Current Step Explanation'] = "Error parsing step information"
        else:
            # Default when field is missing or invalid
            parsed_dict['Current Step'] = 1
            parsed_dict['Current Step Explanation'] = "No step information provided"

        # Parse and validate the planner output
        parsed_dict = self._parse_planner_output(parsed_dict)
        
        return parsed_dict

    def _parse_planner_output(self, planner_dict):
        """
        Parse and validate the planner output dictionary
        """
        # Extract required fields with validation (planner no longer selects actor model)
        required_fields = ["Action", "Reasoning"]
        for field in required_fields:
            if field not in planner_dict:
                self.logger.logger.warning(f"Missing required field '{field}' in planner output")
                planner_dict[field] = ""
        
        # Ensure Current Step and Current Step Explanation exist (should be set earlier)
        if "Current Step" not in planner_dict or "Current Step Explanation" not in planner_dict:
            planner_dict["Current Step"] = 1
            planner_dict["Current Step Explanation"] = "No explanation provided"
                
        return planner_dict

    def _get_system_prompt(self, os_name: str | None = None, guidance_trajectory_example=None):
        effective_os = os_name or self.os_name
        return self._jinja_env.get_template("planner/system.txt").render(
            os_name=effective_os, guidance_trajectory_example=guidance_trajectory_example
        )

    def _resize_down_screenshot(self, screenshot_path, resized_screenshot_path, max_side_length=1024):

        # Open the image file
        image = Image.open(screenshot_path)
        
        # Get the current size
        width, height = image.size

        # Calculate the new size to maintain aspect ratio
        if width > height:
            new_width = max_side_length
            new_height = int(height * (max_side_length / width))
        elif height > width:
            new_height = max_side_length
            new_width = int(width * (max_side_length / height))
        else:
            return screenshot_path

        resized_image = image.resize((new_width, new_height))
        resized_image.save(resized_screenshot_path)

        return resized_screenshot_path
    
    
    def _escape_quotes_in_tuple_string(self, tuple_string: str) -> str:
        """
        Return `tuple_string` with any *inner* single-quotes escaped ( \' ),
        but only if the string is actually wrapped in a pair of single-quotes.

        Examples
        --------
        >>> _escape_quotes_in_tuple_string("(Step 1, foo)")
        '(Step 1, foo)'
        >>> _escape_quotes_in_tuple_string("(Step 1, 'foo' & 'bar')")
        "(Step 1, \\'foo\\' & \\'bar\\')"
        """
        # locate the *first* single-quote
        first_quote = tuple_string.find("'")
        if first_quote == -1:                     # no quotes at all
            return tuple_string

        # locate the *last* single-quote (could be the same as first)
        last_quote = tuple_string.rfind("'")
        if last_quote == first_quote:             # only one quote → nothing to escape
            return tuple_string

        # slice & escape
        prefix   = tuple_string[:first_quote + 1]          # keep opening quote
        content  = tuple_string[first_quote + 1:last_quote]
        suffix   = tuple_string[last_quote:]               # keep closing quote

        escaped_content = content.replace("'", r"\'")      # escape inner quotes
        # Escape a quote only if it is *not* already escaped
        # Negative look-behind (?<!\\) = "previous char is not a backslash"
        escaped_content = re.sub(r"(?<!\\)'", r"\\'", escaped_content)
        return f"{prefix}{escaped_content}{suffix}"

    def _safer_parse_step_response(self, s):
        """
        Robustly parses a string like:
        "(4, The previous step was to scroll to find the 'Aventurine' character, ...)"
        
        Returns: (int, str)
        """
        if not s.strip().startswith("(") or not s.strip().endswith(")"):
            raise ValueError("Not a valid tuple format")

        # Remove outer parentheses
        content = s.strip()[1:-1]
        
        # Split only on the **first** comma
        match = re.match(r"\s*(\d+)\s*,\s*(.+)", content)
        if not match:
            raise ValueError("Could not parse the input")

        step_num = int(match.group(1))
        explanation = match.group(2).strip()

        return (step_num, explanation)
