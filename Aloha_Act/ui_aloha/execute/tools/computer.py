import subprocess
import platform
import pyautogui
import asyncio
import base64
import os
import time
import logging
if platform.system() == "Darwin":
    import Quartz  # uncomment this line if you are on macOS
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4
from screeninfo import get_monitors

from PIL import ImageGrab, Image
from functools import partial

from anthropic.types.beta import BetaToolComputerUse20241022Param

from ui_aloha.execute.tools.base import BaseAnthropicTool, ToolError, ToolResult
from ui_aloha.execute.animation.click_animation import show_click, show_move_to

try:
    from pynput.mouse import Controller as PynputMouse, Button as PynputButton
    _HAVE_PYNPUT = True
except Exception:
    _HAVE_PYNPUT = False

OUTPUT_DIR = "./tmp/outputs"

TYPING_DELAY_MS = 12
TYPING_GROUP_SIZE = 50

Action = Literal[
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "left_press",
    "key_down",
    "key_up",
    "scroll_down",
    "scroll_up",
    "scroll",
    "screenshot",
    "cursor_position",
    "wait",
]


class Resolution(TypedDict):
    width: int
    height: int


MAX_SCALING_TARGETS: dict[str, Resolution] = {
    "XGA": Resolution(width=1024, height=768),  # 4:3
    "WXGA": Resolution(width=1280, height=800),  # 16:10
    "FWXGA": Resolution(width=1366, height=768),  # ~16:9
}


class ScalingSource(StrEnum):
    COMPUTER = "computer"
    API = "api"


class ComputerToolOptions(TypedDict):
    display_height_px: int
    display_width_px: int
    display_number: int | None


def chunks(s: str, chunk_size: int) -> list[str]:
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]


def get_screen_details():
    screens = get_monitors()
    screen_details = []

    # Sort screens by x position to arrange from left to right
    sorted_screens = sorted(screens, key=lambda s: s.x)

    # Loop through sorted screens and assign positions
    primary_index = 0
    for i, screen in enumerate(sorted_screens):
        if i == 0:
            layout = "Left"
        elif i == len(sorted_screens) - 1:
            layout = "Right"
        else:
            layout = "Center"
        
        if screen.is_primary:
            position = "Primary" 
            primary_index = i
        else:
            position = "Secondary"
        screen_info = f"Screen {i + 1}: {screen.width}x{screen.height}, {layout}, {position}"
        screen_details.append(screen_info)

    return screen_details, primary_index


class ComputerTool(BaseAnthropicTool):
    """
    A tool that allows the agent to interact with the screen, keyboard, and mouse of the current computer.
    Adapted for Windows using 'pyautogui'.
    """

    name: Literal["computer"] = "computer"
    api_type: Literal["computer_20241022"] = "computer_20241022"
    width: int
    height: int
    display_num: int | None

    _screenshot_delay = 2.0
    _scaling_enabled = True

    _show_animation = platform.system().lower() != "darwin"    

    @property
    def options(self) -> ComputerToolOptions:
        width, height = self.scale_coordinates(
            ScalingSource.COMPUTER, self.width, self.height
        )
        return {
            "display_width_px": width,
            "display_height_px": height,
            "display_number": self.display_num,
        }

    def to_params(self) -> BetaToolComputerUse20241022Param:
        return {"name": self.name, "type": self.api_type, **self.options}

    def __init__(self, selected_screen: int = 0, is_scaling: bool = True, coords_are_global: bool = False):
        super().__init__()

        # Get screen width and height using Windows command
        self.display_num = None
        self.offset_x = 0
        self.offset_y = 0
        self.selected_screen = selected_screen   
        self.is_scaling = is_scaling
        self.coords_are_global = coords_are_global
        self.width, self.height = self.get_screen_size()     

        # Path to cliclick
        self.cliclick = "cliclick"
        self.key_conversion = {
            "Page_Down": "pagedown",
            "Page_Up": "pageup",
            "Super_L": "win",
            "Escape": "esc",
            "cmd": "command",
        }
        
        system = platform.system()        # Detect platform

        if system.lower() == "windows":
            screens = get_monitors()
            sorted_screens = sorted(screens, key=lambda s: s.x)
            if self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")
            screen = sorted_screens[self.selected_screen]
            bbox = (screen.x, screen.y, screen.x + screen.width, screen.y + screen.height)

        elif system.lower() == "darwin":  # macOS
            max_displays = 32  # Maximum number of displays to handle
            active_displays = Quartz.CGGetActiveDisplayList(max_displays, None, None)[1]
            screens = []
            for display_id in active_displays:
                bounds = Quartz.CGDisplayBounds(display_id)
                screens.append({
                    'id': display_id, 'x': int(bounds.origin.x), 'y': int(bounds.origin.y),
                    'width': int(bounds.size.width), 'height': int(bounds.size.height),
                    'is_primary': Quartz.CGDisplayIsMain(display_id)  # Check if this is the primary display
                })
            sorted_screens = sorted(screens, key=lambda s: s['x'])
            if self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")
            screen = sorted_screens[self.selected_screen]
            bbox = (screen['x'], screen['y'], screen['x'] + screen['width'], screen['y'] + screen['height'])
        else:  # Linux or other OS
            cmd = "xrandr | grep ' primary' | awk '{print $4}'"
            try:
                output = subprocess.check_output(cmd, shell=True).decode()
                resolution = output.strip().split()[0]
                width, height = map(int, resolution.split('x'))
                bbox = (0, 0, width, height)  # Assuming single primary screen for simplicity
            except subprocess.CalledProcessError:
                raise RuntimeError("Failed to get screen resolution on Linux.")
            
        self.offset_x = screen['x'] if system == "Darwin" else screen.x
        self.offset_y = screen['y'] if system == "Darwin" else screen.y
        self.bbox = bbox

    
    async def __call__(
        self,
        *,
        action: Action,
        text: str | None = None,
        coordinate: tuple[int, int] | None = None,
        **kwargs,
    ):
        # Unified dispatcher for better readability and maintenance
        if action == "mouse_move":
            return self._handle_mouse_move(coordinate)
        if action == "left_click_drag":
            return self._handle_left_click_drag(coordinate)

        if action in ("key", "type", "key_down", "key_up"):
            return self._handle_key_actions(action, text, coordinate)

        if action in ("left_click", "right_click", "double_click", "triple_click", "middle_click", "left_press"):
            return self._handle_clicks_and_press(action, coordinate, text)

        if action in ("scroll_down", "scroll_up"):
            return self._handle_simple_scroll(action, coordinate, text)
        if action == "scroll":
            return self._handle_scroll_with_amount(text, coordinate)

        if action in ("screenshot", "cursor_position"):
            return await self._handle_misc(action, text, coordinate)
        if action == "wait":
            return self._handle_wait(text)

        raise ToolError(output=f"Invalid action: {action}", type="hidden", action_base_type="error")

    # ---- Helpers ----
    def _require_coordinate(self, action: Action, coordinate):
        if coordinate is None:
            raise ToolError(output=f"coordinate is required for {action}", action_base_type="error")
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
            raise ToolError(output=f"{coordinate} must be a tuple of length 2", action_base_type="error")
        if not all(isinstance(i, int) for i in coordinate):
            raise ToolError(output=f"{coordinate} must be a tuple of non-negative ints", action_base_type="error")

    def _scale_and_offset(self, coordinate: tuple[int, int]):
        if self.is_scaling:
            x, y = self.scale_coordinates(ScalingSource.API, coordinate[0], coordinate[1])
        else:
            x, y = coordinate
        if self.coords_are_global:
            return x, y
        return x + self.offset_x, y + self.offset_y

    def _offset_or_cursor(self, coordinate: tuple[int, int] | None):
        if coordinate is not None:
            x, y = coordinate
            if self.coords_are_global:
                return x, y
            return x + self.offset_x, y + self.offset_y
        return pyautogui.position()

    def _handle_mouse_move(self, coordinate):
        self._require_coordinate("mouse_move", coordinate)
        x, y = self._scale_and_offset(coordinate)
        pyautogui.moveTo(x, y)
        return ToolResult(output="Mouse move", action_base_type="move")

    def _handle_left_click_drag(self, coordinate):
        self._require_coordinate("left_click_drag", coordinate)
        x, y = self._scale_and_offset(coordinate)
        if platform.system().lower() == "darwin":            
            pyautogui.dragTo(x, y, duration=1.5, button="left") 
        else:
            pyautogui.dragTo(x, y, duration=1.5) 
        return ToolResult(output="Mouse drag", action_base_type="move")

    def _handle_key_actions(self, action: Action, text, coordinate):
        if text is None:
            raise ToolError(output=f"text is required for {action}", action_base_type="error")
        if coordinate is not None:
            raise ToolError(output=f"coordinate is not accepted for {action}", action_base_type="error")
        if not isinstance(text, str):
            raise ToolError(output=f"{text} must be a string", action_base_type="error")

        if action == "key":
            keys = text.split("+")
            for key in keys:
                key = self.key_conversion.get(key.strip(), key.strip()).lower()
                pyautogui.keyDown(key)
            for key in reversed(keys):
                key = self.key_conversion.get(key.strip(), key.strip()).lower()
                pyautogui.keyUp(key)
            return ToolResult(output=f"Press key '{text}'", action_base_type="key")
        if action == "key_down":
            pyautogui.keyDown(text)
            return ToolResult(output=f"Press key '{text}'", action_base_type="key")
        if action == "key_up":
            pyautogui.keyUp(text)
            return ToolResult(output=f"Release key '{text}'", action_base_type="key")
        if action == "type":
            pyautogui.typewrite(text, interval=TYPING_DELAY_MS / 1000)
            return ToolResult(output=f"Type '{text}'", action_base_type="type")

    def _handle_clicks_and_press(self, action: Action, coordinate, text):
        if text is not None:
            raise ToolError(output=f"text is not accepted for {action}", action_base_type="error")

        x, y = self._offset_or_cursor(coordinate)

        def animate_and_click(click_func):
            if self._show_animation:
                show_click(x, y)
                time.sleep(0.7)  # delay actual click by x seconds for better animation
            click_func(x=x, y=y)

        if action == "left_click":
            animate_and_click(pyautogui.click)
            return ToolResult(output="Left click", action_base_type="click")
        if action == "right_click":
            animate_and_click(pyautogui.rightClick)
            return ToolResult(output="Right click", action_base_type="click")
        if action == "middle_click":
            animate_and_click(pyautogui.middleClick)
            return ToolResult(output="Middle click", action_base_type="click")
        if action == "double_click":
            if platform.system().lower() == "darwin":
                try:
                    from pynput import mouse as _pyn_mouse
                    ctl = _pyn_mouse.Controller()
                    ctl.position = (x, y)
                    time.sleep(0.01) 
                    ctl.click(_pyn_mouse.Button.left, 2)
                    return ToolResult(output="Double click", action_base_type="click")
                except Exception as e:
                    pyautogui.doubleClick(x=x, y=y, interval=0.15)
                    return ToolResult(output="Double click", action_base_type="click")
            else:
                animate_and_click(pyautogui.doubleClick)
                return ToolResult(output="Double click", action_base_type="click")
        if action == "triple_click":
            if platform.system().lower() == "darwin":
                try:
                    from pynput import mouse as _pyn_mouse
                    ctl = _pyn_mouse.Controller()
                    ctl.position = (x, y)
                    time.sleep(0.01)  
                    ctl.click(_pyn_mouse.Button.left, 3)
                    return ToolResult(output="Triple click (pynput/macOS)", action_base_type="click")
                except Exception as e:
                    pyautogui.click(x=x, y=y, clicks=3, interval=0.10)
                    return ToolResult(output=f"Triple click (fallback pyautogui/macOS): {e}", action_base_type="click")
            else:
                if self._show_animation:
                    show_click(x, y); time.sleep(0.5)
                pyautogui.click(x=x, y=y, clicks=3, interval=0.10)
                return ToolResult(output="Triple click", action_base_type="click")
        if action == "left_press":
            if self._show_animation:
                show_click(x, y)
                time.sleep(0.5)
            pyautogui.mouseDown(x=x, y=y)
            time.sleep(1)
            pyautogui.mouseUp(x=x, y=y)
            return ToolResult(output="Left press", action_base_type="click")

        return ToolResult(output=f"Performed {action}", action_base_type="unknown")

    def _handle_simple_scroll(self, action: Action, coordinate, text):
        if text is not None:
            raise ToolError(output=f"text is not accepted for {action}", action_base_type="error")
        if coordinate is not None:
            x, y = self._offset_or_cursor(coordinate)
            pyautogui.scroll(-200 if action == "scroll_down" else 200, x=x, y=y)
        else:
            pyautogui.scroll(-200 if action == "scroll_down" else 200)
        return ToolResult(output=f"Scrolled {'down' if action == 'scroll_down' else 'up'}", action_base_type="scroll")

    def _handle_scroll_with_amount(self, text, coordinate):
        if text is None:
            raise ToolError(output="text is required for scroll", action_base_type="error")
        try:
            raw_amount = int(float(text))
        except Exception:
            raise ToolError(output=f"scroll amount must be an integer, got '{text}'", action_base_type="error")

        amt = raw_amount
        if platform.system().lower() == "darwin":
            amt = int(amt / 14)
            if amt == 0 and raw_amount != 0:  # preserve intent for small values
                amt = 1 if raw_amount > 0 else -1

        if coordinate is not None:
            x, y = self._offset_or_cursor(coordinate)
            pyautogui.scroll(amt, x=x, y=y)
        else:
            pyautogui.scroll(amt)

        return ToolResult(output=f"Scroll {amt}", action_base_type="scroll")

    async def _handle_misc(self, action: Action, text, coordinate):
        if text is not None:
            raise ToolError(output=f"text is not accepted for {action}", action_base_type="error")
        if coordinate is not None:
            raise ToolError(output=f"coordinate is not accepted for {action}", action_base_type="error")
        if action == "screenshot":
            return await self.screenshot()
        x, y = pyautogui.position()
        return ToolResult(output=f"Cursor position ({x},{y})", action_base_type="unknown")

    def _handle_wait(self, text):
        try:
            seconds = int(float(text)) if text is not None else 5
        except Exception:
            seconds = 5
        time.sleep(max(0, seconds))
        return ToolResult(output=f"Waited {seconds} seconds", action_base_type="wait")


    async def screenshot(self):
        
        time.sleep(1)
        
        """Take a screenshot of the current screen and return a ToolResult with the base64 encoded image."""
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"screenshot_{uuid4().hex}.png"

        ImageGrab.grab = partial(ImageGrab.grab, all_screens=True)

        # Detect platform
        system = platform.system()

        if system.lower() == "windows":
            # Windows: Use screeninfo to get monitor details
            screens = get_monitors()

            # Sort screens by x position to arrange from left to right
            sorted_screens = sorted(screens, key=lambda s: s.x)

            if self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")

            screen = sorted_screens[self.selected_screen]
            bbox = (screen.x, screen.y, screen.x + screen.width, screen.y + screen.height)

        elif system.lower() == "darwin":  # macOS
            # macOS: Use Quartz to get monitor details
            max_displays = 32  # Maximum number of displays to handle
            active_displays = Quartz.CGGetActiveDisplayList(max_displays, None, None)[1]

            # Get the display bounds (resolution) for each active display
            screens = []
            for display_id in active_displays:
                bounds = Quartz.CGDisplayBounds(display_id)
                screens.append({
                    'id': display_id,
                    'x': int(bounds.origin.x),
                    'y': int(bounds.origin.y),
                    'width': int(bounds.size.width),
                    'height': int(bounds.size.height),
                    'is_primary': Quartz.CGDisplayIsMain(display_id)  # Check if this is the primary display
                })

            # Sort screens by x position to arrange from left to right
            sorted_screens = sorted(screens, key=lambda s: s['x'])

            if self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")

            screen = sorted_screens[self.selected_screen]
            bbox = (screen['x'], screen['y'], screen['x'] + screen['width'], screen['y'] + screen['height'])

        else:  # Linux or other OS
            cmd = "xrandr | grep ' primary' | awk '{print $4}'"
            try:
                output = subprocess.check_output(cmd, shell=True).decode()
                resolution = output.strip().split()[0]
                width, height = map(int, resolution.split('x'))
                bbox = (0, 0, width, height)  # Assuming single primary screen for simplicity
            except subprocess.CalledProcessError:
                raise RuntimeError("Failed to get screen resolution on Linux.")

        # Take screenshot using the bounding box
        screenshot = ImageGrab.grab(bbox=bbox)

        # Set offsets (for potential future use)
        self.offset_x = screen['x'] if system == "Darwin" else screen.x
        self.offset_y = screen['y'] if system == "Darwin" else screen.y

        logging.debug(f"target_dimension {self.target_dimension}")
        
        if not hasattr(self, 'target_dimension'):
            screenshot = self.padding_image(screenshot)
            self.target_dimension = MAX_SCALING_TARGETS["WXGA"]

        # Resize if target_dimensions are specified
        logging.debug(f"offset is {self.offset_x}, {self.offset_y}")
        logging.debug(f"target_dimension is {self.target_dimension}")
        screenshot = screenshot.resize((self.target_dimension["width"], self.target_dimension["height"]))

        # Save the screenshot
        screenshot.save(str(path))

        if path.exists():
            # Return a ToolResult instance instead of a dictionary
            return ToolResult(base64_image=base64.b64encode(path.read_bytes()).decode(), action_base_type="screenshot")
        
        raise ToolError(output=f"Failed to take screenshot: {path} does not exist.", action_base_type="error")

    def padding_image(self, screenshot):
        """Pad the screenshot to 16:10 aspect ratio, when the aspect ratio is not 16:10."""
        _, height = screenshot.size
        new_width = height * 16 // 10

        padding_image = Image.new("RGB", (new_width, height), (255, 255, 255))
        # padding to top left
        padding_image.paste(screenshot, (0, 0))
        return padding_image

    # async def shell(self, command: str, take_screenshot=True) -> ToolResult:
    #     """Run a shell command and return the output, error, and optionally a screenshot."""
    #     _, stdout, stderr = await run(command)
    #     base64_image = None

    #     if take_screenshot:
    #         # delay to let things settle before taking a screenshot
    #         await asyncio.sleep(self._screenshot_delay)
    #         base64_image = (await self.screenshot()).base64_image

    #     return ToolResult(output=stdout, error=stderr, base64_image=base64_image)

    def scale_coordinates(self, source: ScalingSource, x: int, y: int):
        """Scale coordinates to a target maximum resolution."""
        if not self._scaling_enabled:
            return x, y
        ratio = self.width / self.height
        target_dimension = None

        for target_name, dimension in MAX_SCALING_TARGETS.items():
            # allow some error in the aspect ratio - not ratios are exactly 16:9
            if abs(dimension["width"] / dimension["height"] - ratio) < 0.02:
                if dimension["width"] < self.width:
                    target_dimension = dimension
                    self.target_dimension = target_dimension
                    # print(f"target_dimension: {target_dimension}")
                break

        if target_dimension is None:
            # TODO: currently we force the target to be WXGA (16:10), when it cannot find a match
            target_dimension = MAX_SCALING_TARGETS["WXGA"]
            self.target_dimension = MAX_SCALING_TARGETS["WXGA"]

        # should be less than 1
        x_scaling_factor = target_dimension["width"] / self.width
        y_scaling_factor = target_dimension["height"] / self.height
        if source == ScalingSource.API:
            if x > self.width or y > self.height:
                raise ToolError(output=f"Coordinates {x}, {y} are out of bounds", action_base_type="error")
            # scale up
            return round(x / x_scaling_factor), round(y / y_scaling_factor)
        # scale down
        return round(x * x_scaling_factor), round(y * y_scaling_factor)

    def get_screen_size(self):
        system = platform.system()
        if system.lower() == "windows":
            # Use screeninfo to get primary monitor on Windows
            screens = get_monitors()

            # Sort screens by x position to arrange from left to right
            sorted_screens = sorted(screens, key=lambda s: s.x)
            
            if self.selected_screen is None:
                primary_monitor = next((m for m in get_monitors() if m.is_primary), None)
                return primary_monitor.width, primary_monitor.height
            elif self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")
            else:
                screen = sorted_screens[self.selected_screen]
                return screen.width, screen.height

        elif system.lower() == "darwin":
            # macOS part using Quartz to get screen information
            max_displays = 32  # Maximum number of displays to handle
            active_displays = Quartz.CGGetActiveDisplayList(max_displays, None, None)[1]

            # Get the display bounds (resolution) for each active display
            screens = []
            for display_id in active_displays:
                bounds = Quartz.CGDisplayBounds(display_id)
                screens.append({
                    'id': display_id,
                    'x': int(bounds.origin.x),
                    'y': int(bounds.origin.y),
                    'width': int(bounds.size.width),
                    'height': int(bounds.size.height),
                    'is_primary': Quartz.CGDisplayIsMain(display_id)  # Check if this is the primary display
                })

            # Sort screens by x position to arrange from left to right
            sorted_screens = sorted(screens, key=lambda s: s['x'])

            if self.selected_screen is None:
                # Find the primary monitor
                primary_monitor = next((screen for screen in screens if screen['is_primary']), None)
                if primary_monitor:
                    return primary_monitor['width'], primary_monitor['height']
                else:
                    raise RuntimeError("No primary monitor found.")
            elif self.selected_screen < 0 or self.selected_screen >= len(screens):
                raise IndexError("Invalid screen index.")
            else:
                # Return the resolution of the selected screen
                screen = sorted_screens[self.selected_screen]
                return screen['width'], screen['height']

        else:  # Linux or other OS
            cmd = "xrandr | grep ' primary' | awk '{print $4}'"
            try:
                output = subprocess.check_output(cmd, shell=True).decode()
                resolution = output.strip().split()[0]
                width, height = map(int, resolution.split('x'))
                return width, height
            except subprocess.CalledProcessError:
                raise RuntimeError("Failed to get screen resolution on Linux.")
    
    def get_mouse_position(self):
        # TODO: enhance this func
        from AppKit import NSEvent
        from Quartz import CGEventSourceCreate, kCGEventSourceStateCombinedSessionState

        loc = NSEvent.mouseLocation()
        # Adjust for different coordinate system
        return int(loc.x), int(self.height - loc.y)



if __name__ == "__main__":
    computer = ComputerTool()
