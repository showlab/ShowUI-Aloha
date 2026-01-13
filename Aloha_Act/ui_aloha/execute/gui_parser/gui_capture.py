import os
import datetime
import logging
from screeninfo import get_monitors
import pyautogui


class GUICapture:
    def __init__(self, cache_folder: str = '.cache/', selected_screen: int = 0):
        self.task_id = self._now()
        self.cache_folder = os.path.join(cache_folder, self.task_id)
        os.makedirs(self.cache_folder, exist_ok=True)
        self.current_step = 0
        self.selected_screen = selected_screen

    def _now(self) -> str:
        return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def _monitor_region(self) -> tuple[int, int, int, int]:
        screens = sorted(get_monitors(), key=lambda s: s.x)
        if not screens:
            width, height = pyautogui.size()
            return (0, 0, width, height)
        idx = max(0, min(self.selected_screen, len(screens) - 1))
        m = screens[idx]

        # On macOS with multiple monitors, negative x/y can cause issues for PIL/ImageGrab.
        # Fallback to primary bounds if coords look invalid for capture backend.
        if getattr(m, "x", 0) < 0 or getattr(m, "y", 0) < 0:
            width, height = pyautogui.size()
            logging.warning("GUICapture: monitor coords negative; falling back to primary screen bounds")
            return (0, 0, width, height)

        return (m.x, m.y, m.width, m.height)

    def capture_screenshot(self, save_path: str | None = None) -> str:
        if save_path:
            screenshot_path = save_path
        else:
            screenshot_path = os.path.join(self.cache_folder, f'screenshot-{self.current_step}.png')

        left, top, width, height = self._monitor_region()
        try:
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
        except Exception as e:
            logging.error(f"GUICapture: region capture failed ({e}); falling back to full-screen capture")
            screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_path)
        self.current_step += 1
        return screenshot_path


def capture_screenshot(selected_screen: int = 0) -> str:
    """Capture a screenshot and return the image path."""
    gui = GUICapture(selected_screen=selected_screen)
    screenshot_path = gui.capture_screenshot()
    return screenshot_path
