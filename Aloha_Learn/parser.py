# parser.py
import os
import glob
from pathlib import Path

from log_processor import LogProcessor
from screenshot_processor import VideoScreenshotExtractor
from trace_generator import TraceGenerator


def _resolve_project_dir(project_name: str) -> Path:
    """
    Accept either a bare name ('Drag_0') or a full path.
    If bare name, resolve to ./projects/{project_name}.
    """
    p = Path(project_name)
    if p.exists():
        return p.resolve()
    cand = Path.cwd() / "projects" / project_name
    if cand.exists():
        return cand.resolve()
    raise FileNotFoundError(f"Project folder not found. Tried: {p} and {cand}")


def _find_single_log(inputs_dir: Path) -> Path:
    """
    Find exactly one log file in inputs_dir with extensions .txt, .log, .json.
    Match the behavior expected by the existing LogProcessor CLI.
    """
    hits = []
    for ext in ("*.txt", "*.log", "*.json"):
        hits.extend(inputs_dir.glob(ext))
    if not hits:
        raise FileNotFoundError(f"No log files in {inputs_dir} (accepted: .txt, .log, .json)")
    if len(hits) > 1:
        names = ", ".join(h.name for h in hits)
        raise RuntimeError(f"Multiple log files in {inputs_dir}: {names}. Keep only one.")
    return hits[0]


def run_pipeline(project_name: str) -> Path:
    """
    Orchestrate the 3-step pipeline:
      1) parse & merge events -> {project}_processed_log.json
      2) extract screenshots + crops -> {project}_processed_log_sc.json
      3) LLM trace generation -> {project}_trace.json

    Only input: project_name (string). Returns final trace path.
    """
    project_dir = _resolve_project_dir(project_name)
    inputs_dir = project_dir / "inputs"
    if not inputs_dir.exists():
        raise FileNotFoundError(f"Inputs directory not found: {inputs_dir}")

    # ---------- Step 1: process raw log -> processed log ----------
    raw_log = _find_single_log(inputs_dir)
    processed_log_path = project_dir / f"{project_dir.name}_processed_log.json"

    lp = LogProcessor()
    # keep default typing-delay behavior (5.0s) to align with existing logic
    lp.process_log_file(str(raw_log), str(processed_log_path), time_threshold=5.0)

    # ---------- Step 2: screenshots + scaled coords -> *_processed_log_sc.json ----------
    vse = VideoScreenshotExtractor()
    # This function expects the processed log with the exact filename in the project root.
    # It will discover the video and create {project}_processed_log_sc.json and /screenshots.
    _, screenshots_dir, meta = vse.process_project(str(project_dir))

    # ---------- Step 3: generate LLM trace -> {project}_trace.json ----------
    log_sc = project_dir / f"{project_dir.name}_processed_log_sc.json"
    if not log_sc.exists():
        raise FileNotFoundError(f"Expected processed-with-screenshots log not found: {log_sc}")

    out_trace = project_dir / f"{project_dir.name}_trace.json"

    tg = TraceGenerator(
        default_prompt_path="default_prompt.json",
        api_provider="openai",            # or "claude" — adjust here if needed
        openai_model="gpt-4o",
        claude_model="claude-sonnet-4-20250514",
        api_keys_path="config/api_keys.json",
    )
    tg.generate_trace(
        recording_json_path=str(log_sc),
        screenshots_dir=str(screenshots_dir),
        output_trace_path=str(out_trace),
        overall_task=""
    )

    print("=== Pipeline Complete ===")
    print(f"Project: {project_dir.name}")
    print(f"Processed log: {processed_log_path.name}")
    print(f"Screenshots dir: {Path(screenshots_dir).name}")
    print(f"Processed log (+screens): {log_sc.name}")
    print(f"Trace: {out_trace.name}")
    return out_trace


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run full Parser pipeline (1) log → (2) screenshots → (3) trace")
    parser.add_argument("project_name", help="Either a bare name (e.g., 'Drag_0') or a full path to the project folder.")
    args = parser.parse_args()
    run_pipeline(args.project_name)
