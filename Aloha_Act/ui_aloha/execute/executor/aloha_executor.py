import ast
import json
import asyncio
from typing import Any, Dict, cast, List, Union, Callable
import uuid
import logging
import platform


from anthropic.types.beta import BetaToolUseBlock
from ui_aloha.execute.tools import ComputerTool, ToolCollection
from ui_aloha.execute.tools.base import ToolResult, ToolError

log = logging.getLogger(__name__)


class AlohaExecutor:
    def __init__(
        self,
        selected_screen: int = 0,
    ):
        self.selected_screen = selected_screen
        # Determine per-screen offset for multi-monitor setups
        self.offset_x, self.offset_y = self._get_selected_screen_offset()
        logging.info(f"Screen offset for selected_screen={selected_screen}: ({self.offset_x}, {self.offset_y})")

        # Pass coords_are_global=True so ComputerTool won't re-apply offsets
        self.tool_collection = ToolCollection(
            ComputerTool(selected_screen=selected_screen, is_scaling=False, coords_are_global=True)
        )
        
        # Supported high-level actions (uppercase)
        self.supported_actions = {
            "CLICK",
            "RIGHT_CLICK",
            "INPUT",
            "MOVE",
            "HOVER",
            "ENTER",
            "ESC",
            "ESCAPE",
            "PRESS",
            "KEY",
            "HOTKEY",
            "DRAG",
            "SCROLL",
            "DOUBLE_CLICK",
            "TRIPLE_CLICK",
            "WAIT",
            "PAUSE",
            "CONTINUE",
        }

        # Parser dispatch for clarity
        self._parsers: dict[str, Callable[[dict], list[dict]]] = {
            "CLICK": self._parse_click,
            "RIGHT_CLICK": self._parse_right_click,
            "INPUT": self._parse_input,
            "MOVE": self._parse_move,
            "HOVER": self._parse_move,
            "ENTER": self._parse_enter,
            "ESC": self._parse_escape,
            "ESCAPE": self._parse_escape,
            "PRESS": self._parse_press,
            "KEY": self._parse_key_or_hotkey,
            "HOTKEY": self._parse_key_or_hotkey,
            "DRAG": self._parse_drag,
            "SCROLL": self._parse_scroll,
            "DOUBLE_CLICK": self._parse_double_click,
            "TRIPLE_CLICK": self._parse_triple_click,
            "WAIT": self._parse_wait,
            "PAUSE": self._parse_pause,
            "CONTINUE": self._parse_continue,
        }



    def __call__(self, response: str):

        logging.info(f"response: {response}")
        
        # response is expected to be:
        # {'content': "{'action': 'CLICK', 'value': None, 'position': [0.83, 0.15]}, ...", 'role': 'assistant'}, 
        
        # str -> dict
        action_dict = self._format_actor_output(response)  
        
        actions = action_dict["content"]
        
        # Parse the actions from actor
        action_list = self._parse_actor_output(actions)

        logging.info(f"Parsed Action List: {action_list}")

        if action_list is not None and len(action_list) > 0:

            # Convert single-screen-relative coordinates into global coordinates
            for action in action_list:
                coord = action.get("coordinate")
                if coord is not None and isinstance(coord, (list, tuple)) and len(coord) == 2:
                    try:
                        gx = int(coord[0]) + int(self.offset_x)
                        gy = int(coord[1]) + int(self.offset_y)
                        action["coordinate"] = (gx, gy)
                    except Exception:
                        pass

                logging.info(f"Converted Action: {action}")
                # Handle executor-only no-op actions (PAUSE/CONTINUE)
                if action.get("action") == "__no_op__":
                    label = action.get("text") or "NOOP"
                    tool_result_message = {
                        "role": "assistant",
                        "content": f"{label} acknowledged",
                        "type": "action",
                        "action_type": "noop",
                    }
                    yield tool_result_message
                    continue
                
                sim_content_block = BetaToolUseBlock(
                    id=f'toolu_{uuid.uuid4()}',
                    input={'action': action["action"], 'text': action["text"], 'coordinate': action["coordinate"]},
                    name='computer',
                    type='tool_use'
                )

                # Run the asynchronous tool execution in a synchronous context
                tool_result =  asyncio.run(
                    self.tool_collection.run(
                        name=sim_content_block.name,
                        tool_input=cast(dict[str, Any], sim_content_block.input),
                    )
                )
                
                if isinstance(tool_result, ToolResult):
                    logging.info(f"tool_result: {tool_result}")
                    tool_result_message = {"role": "assistant",
                                            "content": tool_result.output,
                                            "type": tool_result.type,
                                            "action_type": tool_result.action_base_type
                                            }
                    yield tool_result_message

                elif isinstance(tool_result, ToolError):
                    logging.error(f"tool_error: {tool_result}")
                    tool_result_message = {"role": "assistant",
                                            "content": tool_result.output,
                                            "type": "error",
                                            "action_type": ""}
                    yield tool_result_message
    
    def _format_actor_output(self, action_output: str | dict) -> Dict[str, Any] | None:
        if isinstance(action_output, dict):
            return action_output
        # Try JSON first, then Python literal as fallback
        try:
            return json.loads(action_output)
        except Exception:
            try:
                return ast.literal_eval(action_output)
            except Exception as e:
                logging.error(f"Error parsing action output: {e}")
                return None
    
    def _parse_actor_output(self, action_item: str | dict) -> Union[List[Dict[str, Any]], None]:
        try:
            if isinstance(action_item, str):
                action_item = ast.literal_eval(action_item)

            logging.info(f"Action Item: {action_item}")

            # normalize action type
            action_name = str(action_item.get("action", "")).upper()
            action_item["action"] = action_name

            if action_name not in self.supported_actions:
                raise ValueError(
                    f"Action {action_name} not supported. Check the output from Actor: {action_item}"
                )

            parser = self._parsers.get(action_name)
            if parser is None:
                raise ValueError(f"No parser for action {action_name}")
            return parser(action_item)

        except Exception as e:
            logging.error(f"Error {e} in parsing output: {action_item}")
            return None

    # ---------------------
    # Parser implementations
    # ---------------------
    def _ensure_position_tuple(self, item: dict) -> tuple[int, int]:
        x, y = item["position"]
        return int(x), int(y)

    def _parse_click(self, item: dict) -> list[dict]:
        x, y = self._ensure_position_tuple(item)
        return [
            {"action": "mouse_move", "text": None, "coordinate": (x, y)},
            {"action": "left_click", "text": None, "coordinate": (x, y)},
        ]

    def _parse_right_click(self, item: dict) -> list[dict]:
        x, y = self._ensure_position_tuple(item)
        return [
            {"action": "mouse_move", "text": None, "coordinate": (x, y)},
            {"action": "right_click", "text": None, "coordinate": (x, y)},
        ]

    def _parse_input(self, item: dict) -> list[dict]:
        if "text" in item:
            text = item["text"]
        elif "value" in item:
            text = item["value"]
        else:
            raise ValueError(f"Input action does not contain 'text' or 'value': {item}")
        return [{"action": "type", "text": text, "coordinate": None}]

    def _parse_move(self, item: dict) -> list[dict]:
        x, y = self._ensure_position_tuple(item)
        return [{"action": "mouse_move", "text": None, "coordinate": (x, y)}]

    def _parse_enter(self, item: dict) -> list[dict]:
        return [{"action": "key", "text": "Enter", "coordinate": None}]

    def _parse_escape(self, item: dict) -> list[dict]:
        return [{"action": "key", "text": "Escape", "coordinate": None}]

    def _parse_press(self, item: dict) -> list[dict]:
        x, y = self._ensure_position_tuple(item)
        return [
            {"action": "mouse_move", "text": None, "coordinate": (x, y)},
            {"action": "left_press", "text": None, "coordinate": None},
        ]

    def _parse_key_or_hotkey(self, item: dict) -> list[dict]:
        v = item.get("value")
        if isinstance(v, list):
            return [{"action": "key", "text": key, "coordinate": None} for key in v]
        return [{"action": "key", "text": v, "coordinate": None}]

    def _parse_drag(self, item: dict) -> list[dict]:
        # Support multiple schema variants for drag coordinates:
        # - { value: [x1,y1], position: [x2,y2] }  (existing)
        # - { from: [x1,y1], to: [x2,y2] }
        # - { start: [x1,y1], end: [x2,y2] }
        def to_xy(val, name: str) -> tuple[int, int]:
            if isinstance(val, (list, tuple)) and len(val) >= 2:
                return int(val[0]), int(val[1])
            raise ValueError(f"Invalid coordinate for '{name}': {val}")

        start = None
        for k in ("from", "start", "value"):
            if k in item and item[k] is not None:
                start = to_xy(item[k], k)
                break
        end = None
        for k in ("to", "end", "position"):
            if k in item and item[k] is not None:
                end = to_xy(item[k], k)
                break
        if start is None or end is None:
            raise ValueError(f"DRAG action requires start and end coordinates; got: {item}")

        x1, y1 = start
        x2, y2 = end
        return [
            {"action": "mouse_move", "text": None, "coordinate": (x1, y1)},
            {"action": "left_click_drag", "text": None, "coordinate": (x2, y2)},
        ]

    def _parse_double_click(self, item: dict) -> list[dict]:
        x, y = self._ensure_position_tuple(item)
        return [
            {"action": "mouse_move", "text": None, "coordinate": (x, y)},
            {"action": "double_click", "text": None, "coordinate": None},
        ]

    def _parse_triple_click(self, item: dict) -> list[dict]:
        x, y = self._ensure_position_tuple(item)
        return [
            {"action": "mouse_move", "text": None, "coordinate": (x, y)},
            {"action": "triple_click", "text": None, "coordinate": None},
        ]

    def _parse_wait(self, item: dict) -> list[dict]:
        # Accept duration from 'duration', 'time', or 'value'; default to 5 seconds
        seconds = (item.get("ms", 5000) / 1000) or item.get("seconds", 5)
        return [{"action": "wait", "text": str(seconds), "coordinate": None}]

    def _parse_pause(self, item: dict) -> list[dict]:
        # No operation needed; executor just acknowledges
        return [{"action": "__no_op__", "text": "PAUSE", "coordinate": None}]

    def _parse_continue(self, item: dict) -> list[dict]:
        # No operation needed; executor just acknowledges
        return [{"action": "__no_op__", "text": "CONTINUE", "coordinate": None}]

    def _parse_scroll(self, item: dict) -> list[dict]:
        # Expect value as scalar (vertical) or [scroll_x, scroll_y], and optionally a position
        val = item.get("value")
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            _, scroll_y = val
        else:
            scroll_y = val

        if scroll_y is None:
            raise ValueError(f"Scroll action missing 'value': {item}")
        try:
            scroll_y = int(float(scroll_y))
        except Exception:
            raise ValueError(f"Scroll 'value' must be numeric, got: {val}")

        refined_output: list[dict] = []
        coord = None
        if "position" in item and item["position"] is not None:
            x, y = item["position"]
            coord = (int(x), int(y))
            refined_output.append({"action": "mouse_move", "text": None, "coordinate": coord})

        # Convention: positive value means scroll down. pyautogui uses positive = up.
        signed_amount = -scroll_y
        refined_output.append({"action": "scroll", "text": str(signed_amount), "coordinate": coord})
        return refined_output


    def _get_selected_screen_offset(self) -> tuple[int, int]:
        from screeninfo import get_monitors
        import subprocess

        system = platform.system().lower()

        if system == "windows":
            screens = get_monitors()
            sorted_screens = sorted(screens, key=lambda s: s.x)
            if self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")
            screen = sorted_screens[self.selected_screen]
            return int(screen.x), int(screen.y)

        if system == "darwin":
            import Quartz  # type: ignore
            max_displays = 32
            active_displays = Quartz.CGGetActiveDisplayList(max_displays, None, None)[1]
            screens: list[dict] = []
            for display_id in active_displays:
                bounds = Quartz.CGDisplayBounds(display_id)
                screens.append(
                    {
                        "id": display_id,
                        "x": int(bounds.origin.x),
                        "y": int(bounds.origin.y),
                        "width": int(bounds.size.width),
                        "height": int(bounds.size.height),
                        "is_primary": Quartz.CGDisplayIsMain(display_id),
                    }
                )
            sorted_screens = sorted(screens, key=lambda s: s["x"])
            if self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")
            screen = sorted_screens[self.selected_screen]
            return int(screen["x"]), int(screen["y"])

        # Linux and others: assume primary is at (0,0)
        try:
            _ = subprocess.check_output("xrandr", shell=True)
        except Exception:
            pass
        return 0, 0
