import os
import json
import logging
from typing import List, Dict, Optional

log = logging.getLogger(__name__)

class TrajectoryManager:
    """
    Manages user trajectory data for task execution recordings.
    Provides methods to load, access, and format trajectory information.
    """
    def __init__(self, base_path: str = r"./cache"):

        self.base_path = base_path
        
        
    def get_full_trace(self, trace_name: str) -> Optional[Dict]:
        """
        Load trace data for a specific trace.
        """
        # Layout: base_path/trace_name/trace.json
        candidate_paths = [
            os.path.join(self.base_path, f"{trace_name}"),
            os.path.join(self.base_path, f"{trace_name}.json"),
            os.path.join(self.base_path, trace_name, "trace.json")
        ]

        file_path = None
        for path in candidate_paths:
            if os.path.exists(path):
                file_path = path
                break
        if file_path is None:
            # Fall back to the first candidate for error message
            file_path = candidate_paths[0]
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                trace_data = json.load(f)
            
            return trace_data
        
        except FileNotFoundError:
            log.warning("Trace file not found: %s", file_path)
            return None
        except json.JSONDecodeError:
            log.warning("JSON parsing error: %s", file_path)
            return None


    def get_trajectory_in_context(self, trace_name: str, formatting_string: bool = True) -> Optional[str]:
        """
        Get the in-context example for the given trace.
        
        Args:
            trace_name (str): Name of the trace
            formatting_string (bool): Whether to format the output as string (True) or list (False)
            
        Returns:
            Optional[str]: Formatted in-context example string/list or None if trace not found
        """
        
        trace_data = self.get_full_trace(trace_name)
        if not trace_data:
            return None
        
        steps = trace_data.get("trajectory", [])
        context_steps = []

        for action in steps:
            
            if "milestone" in action:  # filter out 'milestones'
                continue
            
            step_idx = action['step_idx']
            step_caption = action['caption']
            step_action = step_caption['action']
            context_steps.append(f"Step [{step_idx}]: {step_action}")
        
        if formatting_string:
            return "\n".join(context_steps)
        else:
            return context_steps
