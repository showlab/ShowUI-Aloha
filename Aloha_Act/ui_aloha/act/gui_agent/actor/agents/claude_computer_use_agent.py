import json
from jinja2 import Environment, FileSystemLoader

from ui_aloha.act.utils.path_utils import prompt_templates_path
from ui_aloha.act.gui_agent.llm.llm_utils import encode_image

try:
    import anthropic
    from anthropic.types.beta import BetaTextBlock, BetaToolUseBlock
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    BetaTextBlock = None
    BetaToolUseBlock = None


class ClaudeComputerUseAgent:
    def __init__(self, api_key, logger=None):
        if ANTHROPIC_AVAILABLE and api_key:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self.client = None
        self.logger = logger
        
        # Configuration
        self.DISPLAY_WIDTH = 1024
        self.DISPLAY_HEIGHT = 768
        
        # Action type conversion mapping
        self.action_type_convert = {
            "left_click": "CLICK",
            "double_click": "DOUBLE_CLICK",
            "triple_click": "TRIPLE_CLICK", 
            "mouse_move": "MOVE",
            "scroll": "SCROLL",
            "wait": "WAIT",
            "key": "KEY",
            "type": "TYPE",
            "left_click_drag": "DRAG",
            "keypress": "KEY",
        }
    
    def execute(self, instruction, screenshot_path, system_prompt, logging_dir):
        """Execute Claude Computer Use agent action"""
        
        if not ANTHROPIC_AVAILABLE or not self.client:
            error_msg = "Anthropic library not available or API key not provided"
            if self.logger:
                self.logger.logger.error(error_msg)
            return {"action": "ERROR", "value": error_msg, "position": [0, 0]}, False
        
        screenshot_base64 = encode_image(screenshot_path)
        
        try:
            # Render user instruction template via Jinja2
            templates_dir = prompt_templates_path()
            env = Environment(
                loader=FileSystemLoader(str(templates_dir)),
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
            )
            user_text = env.get_template("actor/user_cua.txt").render(task=instruction)

            response = self.client.beta.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                tools=[{
                    "type": "computer_20250124",
                    "name": "computer",
                    "display_width_px": self.DISPLAY_WIDTH,
                    "display_height_px": self.DISPLAY_HEIGHT,
                    "display_number": 1,
                }],
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_base64,
                            },
                        },
                        {
                            "type": "text", 
                            "text": user_text,
                        }
                    ]
                }],
                betas=["computer-use-2025-01-24"]
            )
            
            # Log raw response
            if self.logger:
                self.logger.log_json({"response": str(response)}, "actor_claude_computer_use_raw_response.json", logging_dir)
            
            action_json = self._parse_response(response)
            
            # Log parsed action
            if self.logger:
                self.logger.log_json(action_json, "actor_claude_computer_use_parsed_action.json", logging_dir)
            
            return action_json, action_json.get("action") == "STOP"
            
        except Exception as e:
            error_msg = f"Error processing claude-computer-use response: {e}"
            if self.logger:
                self.logger.logger.error(error_msg)
                self.logger.log_error(e, {"mode": "claude-computer-use"}, target_dir=logging_dir)
            
            return {"action": "ERROR", "value": str(e), "position": [0, 0]}, False
    
    def _parse_response(self, response):
        """Parse Claude Computer Use response into standardized action format"""
        
        action_json = {}
        cua_output_item = response.content
        computer_call_found = False
        
        for item in cua_output_item:
            if isinstance(item, BetaTextBlock):
                if self.logger:
                    self.logger.logger.info(f"claude_computer_use: reasoning={item.text}")
            elif isinstance(item, BetaToolUseBlock):
                action = item.input
                action_type = action.get("action", "")
                
                if action_type in self.action_type_convert and action_type == "left_click":  # TODO: support more actions
                    computer_call_found = True
                    coord = action['coordinate']
                    if self.logger:
                        self.logger.logger.info(f"claude_computer_use: coord={coord}")
                    
                    # Resolution scaling to 1920x1080
                    coord[0] = int(coord[0] / self.DISPLAY_WIDTH * 1920)
                    coord[1] = int(coord[1] / self.DISPLAY_HEIGHT * 1080)
                    
                    if self.logger:
                        self.logger.logger.info(f"claude_computer_use: scaled_coord={coord}")
                    
                    action_json = {
                        "action": self.action_type_convert[action_type],
                        "value": "",
                        "position": [coord[0], coord[1]],
                    }
                else:
                    if self.logger:
                        self.logger.logger.info(f"claude_computer_use: unsupported action_type={action_type}")
        
        if not computer_call_found:
            action_json = {"action": "ERROR", "value": "No valid computer action found", "position": [0, 0]}
        
        return action_json
