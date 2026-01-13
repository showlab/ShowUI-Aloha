import os
import json
import logging
from typing import Sequence

from jinja2 import Environment, FileSystemLoader
from ui_aloha.act.gui_agent.llm.run_llm import run_llm

log = logging.getLogger(__name__)


class TrajectoryRefiner:
    """
    Adapt a recorded trajectory to a new instruction with minimal edits.

    - Input: an existing trajectory (list of "Step [n]: ..." strings or a trace JSON path)
             and a new instruction string.
    - Output: adapted trajectory as a newline-joined string of "Step [n]: ..." lines.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        max_tokens: int = 1024,
        api_keys: dict | None = None,
    ) -> None:
        self.system_prompt = (
            "You are a trajectory adaptation assistant. You will receive an existing, ordered set "
            "of execution steps (a trajectory) and a new instruction describing a similar but not "
            "identical task. Your goal is to adapt the original steps to achieve the new instruction "
            "with minimal changes. Preserve the step order and count when reasonable. Only modify the "
            "content of steps that must change to satisfy the new instruction."
        )
        templates_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "prompt_templates")
        )
        self._jinja_env = Environment(
            loader=FileSystemLoader(templates_dir), autoescape=False, trim_blocks=True, lstrip_blocks=True
        )
        self.model = model
        self.max_tokens = max_tokens
        self.api_keys = api_keys or {"OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")}

    def _steps_from_trace_json(self, trace_path: str) -> list[str]:
        with open(trace_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        steps_out: list[str] = []

        if isinstance(data, dict) and isinstance(data.get("trajectory"), list):
            for item in data["trajectory"]:
                if not isinstance(item, dict) or "milestone" in item:
                    continue
                idx = item.get("step_idx")
                cap = item.get("caption", {}) if isinstance(item.get("caption"), dict) else {}
                action = cap.get("action") or item.get("action") or item.get("text")
                if idx is not None and action:
                    steps_out.append(f"Step [{idx}]: {action}")
            if steps_out:
                return steps_out

        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return [x.strip() for x in data]

        if isinstance(data, list):
            for i, item in enumerate(data, start=1):
                if isinstance(item, dict):
                    action = item.get("action") or item.get("caption") or item.get("text")
                else:
                    action = str(item)
                steps_out.append(f"Step [{i}]: {action}")
        return steps_out

    def _normalize_steps(self, steps: Sequence[str]) -> list[str]:
        return [str(s).strip() for s in steps if str(s).strip()]

    def _build_prompt(self, steps: Sequence[str], new_instruction: str) -> str:
        steps_text = "\n".join(self._normalize_steps(steps))
        return self._jinja_env.get_template(
            "trajectory_refiner/trajectory_refiner.txt"
        ).render(trajectory=steps_text, new_instruction=new_instruction)

    def _call_llm(self, prompt: str) -> str:
        response, _usage = run_llm(
            messages=prompt,
            system=self.system_prompt,
            llm=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            api_keys=self.api_keys,
        )
        return response

    def run(
        self,
        trajectory_source: list[str] | str,
        new_instruction: str,
        logging_dir: str = "./cache",
    ) -> str:
        """
        Adapt an existing trajectory to the new instruction.

        - trajectory_source: either a list[str] of step lines, or a JSON file path.
        - new_instruction: textual instruction to adapt towards.

        Returns adapted steps as a newline-joined string.
        """
        if isinstance(trajectory_source, str):
            steps = self._steps_from_trace_json(trajectory_source)
            log.info("Loaded %d steps from %s", len(steps), trajectory_source)
        else:
            steps = self._normalize_steps(trajectory_source)
            log.info("Using %d provided steps", len(steps))

        prompt = self._build_prompt(steps, new_instruction)

        try:
            os.makedirs(logging_dir, exist_ok=True)
            log_path = os.path.join(logging_dir, "send_to_trajectory_refiner.log")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(
                    [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            log.warning("Failed to write trajectory refiner log: %s", e)

        adapted = self._call_llm(prompt)
        return str(adapted).strip()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    import argparse

    parser = argparse.ArgumentParser(description="Adapt a trajectory to a new instruction")
    parser.add_argument("--trace", type=str, help="Path to a trace JSON, e.g., trace_data/example_trace.json")
    parser.add_argument("--instruction", type=str, required=True, help="New instruction to adapt towards")
    args = parser.parse_args()

    refiner = TrajectoryRefiner()
    source = args.trace if args.trace else []
    result = refiner.run(source, args.instruction)
    print(result)
