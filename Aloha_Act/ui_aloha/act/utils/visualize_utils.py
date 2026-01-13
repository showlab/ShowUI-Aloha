import ast
import json
from typing import Any, Dict, Tuple

from PIL import Image

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_action_vis(action: Dict[str, Any] | str, screenshot_path: str, action_vis_path: str) -> None:
    """Plot the action coordinate on the screenshot and save the visualization."""
    
    def _extract_coord_xy(action_obj: Dict[str, Any]) -> Tuple[int, int] | None:
        """Best-effort extraction of an (x, y) position from common shapes."""
        pos = action_obj.get("position")
        if pos is None:
            return None

        # Handle list/tuple directly
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                return int(pos[0]), int(pos[1])
            except Exception:
                return None

        # Handle string like "(x, y)" or "[x, y]"
        try:
            parsed = ast.literal_eval(str(pos))
            if isinstance(parsed, (list, tuple)) and len(parsed) == 2:
                return int(parsed[0]), int(parsed[1])
        except Exception:
            return None

        return None

    screenshot = Image.open(screenshot_path)
    plt.figure(figsize=(12, 8))
    plt.imshow(screenshot)

    # Normalize action content
    try:
        action_content: Dict[str, Any]
        if isinstance(action, str):
            action_content = json.loads(action)
        else:
            # actor returns {"content": {...}, "role": "assistant"}
            action_content = action.get("content", action)

        pos = _extract_coord_xy(action_content)
        if pos:
            x, y = pos
            plt.scatter(x, y, color="red", marker="x", s=100)
            
    except Exception:
        # Ignore viz errors entirely
        pass

    plt.title(f"actor: {str(action_content)[:180]}")
    plt.tight_layout()
    plt.savefig(action_vis_path)
    plt.close()
