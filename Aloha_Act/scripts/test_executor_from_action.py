#!/usr/bin/env python3
"""
Test runner for the local executor that accepts:

Examples:

Execute from a raw JSON string (see oai_operator_agent.py for format):
    python scripts/test_executor_from_action.py \
        --input '{"action": "SCROLL", "value": [0, 300], "position": [960, 540]}'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

from ui_aloha.execute.executor.aloha_executor import AlohaExecutor


def load_action_from_input(arg: str) -> Dict[str, Any]:
    """Load an action dict from a file path or JSON string.

    - If `arg` is a file path, read JSON from it.
    - Otherwise, attempt to parse `arg` as a JSON string.
    """
    if os.path.exists(arg) and os.path.isfile(arg):
        with open(arg, "r", encoding="utf-8") as f:
            return json.load(f)
    try:
        return json.loads(arg)
    except Exception as e:
        raise ValueError(f"Input is neither a file path nor valid JSON. got='{arg}', error={e}")


def main():
    parser = argparse.ArgumentParser(description="Test the local executor with a single action.")

    parser.add_argument("--selected-screen", type=int, default=0, help="Screen index to target (default: 0)")
    parser.add_argument("--dry-run", action="store_true", help="Only parse and print low-level actions; do not execute")
    parser.add_argument("--verbose", action="store_true", help="Print extra details")

    args = parser.parse_args()

    # Build the high-level action dict in the actor format
    action_dict = load_action_from_input(args.input)

    if not isinstance(action_dict, dict) or "action" not in action_dict:
        print("Input must be a dict containing an 'action' key.", file=sys.stderr)
        sys.exit(2)

    if args.verbose:
        print("Loaded action:")
        print(json.dumps(action_dict, indent=2))

    # Wrap in the expected executor message format
    message = {"role": "assistant", "content": action_dict}

    # Instantiate executor
    executor = AlohaExecutor(selected_screen=args.selected_screen)
    low_level = executor._parse_actor_output(action_dict)  # type: ignore[attr-defined]

    if args.dry_run:
        # In dry-run, show the internal parse into tool calls without executing
        # Note: Using private method _parse_actor_output for debugging/testing convenience
        if low_level is None:
            print("Failed to parse action into low-level tool calls.", file=sys.stderr)
            sys.exit(1)
        print("Low-level tool calls (dry-run):")
        for i, step in enumerate(low_level, 1):
            print(f"  {i}. {step}")
        return

    # Execute the action and stream results
    print("Executing action via AlohaExecutor...")
    for msg in executor(message):
        kind = msg.get("type")
        base = msg.get("action_type")
        content = msg.get("content")
        if args.verbose:
            print(json.dumps(msg, indent=2))
        else:
            print(f"[{kind or 'msg'}] {base or ''}: {content}")


if __name__ == "__main__":
    main()

