"""Actor orchestrator that routes to concrete backend agents."""

from jinja2 import Environment, FileSystemLoader
from ui_aloha.act.utils.path_utils import prompt_templates_path
from ui_aloha.act.utils.logger_utils import LoggerUtils

# Import the separate agent modules
from ui_aloha.act.gui_agent.actor.agents import (
    OAIOperatorAgent,
    ClaudeComputerUseAgent,
    UITarsAgent
)

class AlohaActor:
    """High-level actor that selects and executes a specific agent backend."""

    def __init__(
        self,
        api_keys: dict | None = None,
        model: str = "oai-operator",
        os_name: str = "windows",
    ):
        self.api_keys = api_keys
        self.model = model
        self.os_name = os_name

        # Initialize logger
        self.logger = LoggerUtils(component_name="actor")
        
        # Extract API keys
        if api_keys:
            operator_openai_api_key = api_keys.get("OPERATOR_OPENAI_API_KEY") or api_keys.get("OPENAI_API_KEY", "")
            claude_api_key = api_keys.get("CLAUDE_API_KEY", "")
        else:
            operator_openai_api_key = ""
            claude_api_key = ""
            

        # Initialize agent modules
        self.oai_operator_agent = OAIOperatorAgent(
            api_key=operator_openai_api_key,
            logger=self.logger
        )
        
        self.claude_computer_use_agent = ClaudeComputerUseAgent(
            api_key=claude_api_key,
            logger=self.logger
        )
        
        self.ui_tars_agent = UITarsAgent(
            logger=self.logger
        )

        # Jinja2 template environment
        templates_dir = prompt_templates_path()
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Define system prompts via Jinja2
        self.oai_operator_system_prompt = self._jinja_env.get_template(
            "actor/system_cua.txt").render(os_name=self.os_name)
        self.claude_cua_system_prompt = self._jinja_env.get_template(
            "actor/system_cua.txt").render(os_name=self.os_name)
        self.uitars_grounding_system_prompt = self._jinja_env.get_template(
            "actor/system_ui_tars.txt").render()


    def __call__(
        self,
        mode: str | None = None,
        messages: str | dict = "",
        screenshot_path: str = "",
        logging_dir: str = ".cache/",
    ):
        """Execute the selected agent and return its next action.

        Args:
            mode: Optional override; one of "oai-operator", "claude-computer-use", "ui-tars".
            messages: Planner output or instruction string.
            screenshot_path: Path to the current UI screenshot.
            logging_dir: Directory to store logs.

        Returns:
            (action_dict_wrapped, complete_flag)
        """

        # Ensure task is properly formatted
        if isinstance(messages, dict):
            task = messages
        else:
            task = messages

        effective_mode = (mode or self.model)
        self.logger.logger.info(f"AlohaActor Mode: {effective_mode}")

        # -------------------------------
        # Execute the appropriate agent based on mode
        # -------------------------------
        if effective_mode == "oai-operator":
            response, complete_flag = self.oai_operator_agent.execute(
                instruction=task,
                screenshot_path=screenshot_path,
                os_name=self.os_name,
                system_prompt=self.oai_operator_system_prompt,
                logging_dir=logging_dir
            )
        
        elif effective_mode == "claude-computer-use":
            response, complete_flag = self.claude_computer_use_agent.execute(
                instruction=task,
                screenshot_path=screenshot_path,
                system_prompt=self.claude_cua_system_prompt,
                logging_dir=logging_dir
            )
        
        elif effective_mode == "ui-tars":  # qwen related
            response, complete_flag = self.ui_tars_agent.execute(
                instruction=task,
                screenshot_path=screenshot_path,
                system_prompt=self.uitars_grounding_system_prompt,
                logging_dir=logging_dir
            )
        
        else:
            error_msg = f"Invalid mode for AlohaActor: {effective_mode}"
            self.logger.logger.error(error_msg)
            response = {"action": "ERROR", "value": error_msg, "position": [0, 0]}
            complete_flag = False
        
        
        self.logger.log_json(response, f"actor_{effective_mode}_action.json", logging_dir)

        # Return in the original format for backward compatibility
        final_response = {"content": response, "role": "assistant"}
        return final_response, complete_flag
