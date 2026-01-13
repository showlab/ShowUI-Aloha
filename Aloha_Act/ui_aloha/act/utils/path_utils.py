from __future__ import annotations

from pathlib import Path

# Base directory for the GUI agent package
_GUI_AGENT_DIR = Path(__file__).resolve().parent.parent / "gui_agent"
_PROMPT_TEMPLATES_DIR = _GUI_AGENT_DIR / "prompt_templates"


def prompt_templates_path(*relative_parts: str) -> Path:
    """Return the absolute Path to the prompt_templates directory (optionally joined with sub-paths)."""
    return _PROMPT_TEMPLATES_DIR.joinpath(*relative_parts)
