import pyautogui
import asyncio
import sys
import time
import logging
from ui_aloha.execute.tools.computer import ComputerTool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


async def test_animations():
    
    # Initialize the computer tool
    computer = ComputerTool()
    
    log.info("Testing mouse move animation...")
    
    await computer(action="key_down", text='alt')
    await computer(action="mouse_move", coordinate=(1600, 45))

    await computer(action="left_click", coordinate=(1600, 45))
    await asyncio.sleep(1)
    await computer(action="key_up", text='alt')

    # Wait for animations to comple1e
    log.info("Waiting for animations to complete...")
    await asyncio.sleep(3)
    
    log.info("Test completed")


def test_pyautogui_basic_demo():
    pyautogui.moveTo(x=600, y=400, duration=0.4)
    time.sleep(0.2)
    pyautogui.click(x=600, y=400)

if __name__ == "__main__":
    # asyncio.run(test_animations())
    test_pyautogui_basic_demo()
